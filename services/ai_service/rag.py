"""Retrieval-augmented generation over the support knowledge base.

Pipeline, and why each stage exists:

    knowledge article        the source of truth, owned by Service Operations
        -> document          registered with a content hash so a re-index is
                             triggered by content change, not by a schedule
        -> chunk             sectioned on headings and paragraph boundaries,
                             because splitting mid-sentence destroys the very
                             context retrieval is supposed to supply
        -> embedding         vector per chunk
        -> vector search     top-k by cosine similarity, with a floor
        -> context           only chunks above the floor, with their article ids
        -> LLM               grounded generation
        -> cited answer      every policy claim carries [KB-xxx]

The similarity floor is the important detail.  Without it, top-k always returns
k chunks, so a question the knowledge base does not cover still gets three
confident-looking extracts and the model answers from them.  With it, retrieval
can return nothing and the template's "the knowledge base does not cover this"
path fires.

Local mode uses the deterministic embedding in ``providers.LocalProvider`` and
computes cosine similarity in Python.  Cloud mode stores ``VECTOR(FLOAT, 768)``
and uses ``VECTOR_COSINE_SIMILARITY`` inside Snowflake, so the corpus never
leaves the account; the SQL is in ``snowflake/08-ai/04-rag-vector-search.sql``.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import re
from dataclasses import dataclass

from common.config import get_settings

log = logging.getLogger("ai.rag")
_settings = get_settings()

MAX_CHUNK_CHARS = 450
MIN_CHUNK_CHARS = 120
SIMILARITY_FLOOR = 0.15
DEFAULT_TOP_K = 3

# TODO: no overlap between chunks yet. A rule that straddles a paragraph
# boundary can lose its exception clause. Fixed-window overlap is the usual
# answer but it inflates the corpus; revisit once there are more articles.


@dataclass
class RetrievedChunk:
    chunk_id: str
    article_id: str
    title: str
    text: str
    score: float


def chunk_document(content: str, max_chars: int = MAX_CHUNK_CHARS) -> list[tuple[str, str]]:
    """Split on paragraph boundaries, then pack up to ``max_chars``.

    Returns (section_title, chunk_text).  Packing whole paragraphs rather than
    slicing at a character count is what keeps a policy rule and its exception
    in the same chunk - separating them is how a RAG system ends up citing the
    rule while omitting "except when...".
    """
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", content) if p.strip()]
    chunks: list[tuple[str, str]] = []
    buf: list[str] = []
    section = ""
    for para in paragraphs:
        if para.startswith("#"):
            section = para.lstrip("# ").strip()
            continue
        if buf and sum(len(x) for x in buf) + len(para) > max_chars:
            chunks.append((section, "\n\n".join(buf)))
            buf = []
        buf.append(para)
    if buf:
        text = "\n\n".join(buf)
        if chunks and len(text) < MIN_CHUNK_CHARS:
            prev_section, prev_text = chunks[-1]
            chunks[-1] = (prev_section, prev_text + "\n\n" + text)
        else:
            chunks.append((section, text))
    return chunks


def build_corpus() -> int:
    """(Re)build KB_DOCUMENT and KB_CHUNK from RAW.RAW_SUP_KNOWLEDGE_ARTICLE."""
    from local_warehouse.warehouse import shared  # noqa: PLC0415

    from .providers import build_provider  # noqa: PLC0415

    con = shared()
    provider = build_provider()
    articles = con.execute(
        "SELECT ARTICLE_ID, TITLE, CATEGORY, OWNER, SOURCE_URI, CONTENT, LAST_REVIEWED "
        "FROM ACME_EDP.RAW.RAW_SUP_KNOWLEDGE_ARTICLE ORDER BY ARTICLE_ID").fetchall()

    con.execute("DELETE FROM ACME_EDP.AI.KB_CHUNK")
    con.execute("DELETE FROM ACME_EDP.AI.KB_DOCUMENT")

    doc_rows, chunk_specs = [], []
    for article_id, title, category, owner, uri, content, reviewed in articles:
        content_hash = hashlib.md5((content or "").encode(), usedforsecurity=False).hexdigest()
        doc_id = f"DOC-{article_id}"
        doc_rows.append([doc_id, article_id, title, category, owner, uri, content,
                         content_hash, reviewed, True])
        for idx, (section, text) in enumerate(chunk_document(content or "")):
            chunk_specs.append({
                "chunk_id": f"{doc_id}-C{idx:03d}", "document_id": doc_id,
                "article_id": article_id, "index": idx, "text": text,
                "section": section or title})

    con.executemany(
        "INSERT INTO ACME_EDP.AI.KB_DOCUMENT (DOCUMENT_ID, ARTICLE_ID, TITLE, CATEGORY, OWNER,"
        " SOURCE_URI, CONTENT, CONTENT_HASH, LAST_REVIEWED, IS_ACTIVE, _LOADED_AT)"
        " VALUES (?,?,?,?,?,?,?,?,?,?, CURRENT_TIMESTAMP)", doc_rows)

    # Corpus term statistics for the offline TF-IDF embedder.  Computed once at
    # index time and persisted, so query-time embedding uses exactly the same
    # weighting as index-time embedding.
    _persist_term_stats(con, provider, [c["text"] for c in chunk_specs])

    vectors = asyncio.run(provider.embed([c["text"] for c in chunk_specs]))
    chunk_rows = [[c["chunk_id"], c["document_id"], c["article_id"], c["index"], c["text"],
                   max(1, len(c["text"]) // 4), c["section"], v,
                   getattr(provider, "model", provider.name)]
                  for c, v in zip(chunk_specs, vectors, strict=True)]
    con.executemany(
        "INSERT INTO ACME_EDP.AI.KB_CHUNK (CHUNK_ID, DOCUMENT_ID, ARTICLE_ID, CHUNK_INDEX,"
        " CHUNK_TEXT, CHUNK_TOKENS, SECTION_TITLE, EMBEDDING, EMBEDDING_MODEL, EMBEDDED_AT)"
        " VALUES (?,?,?,?,?,?,?,?,?, CURRENT_TIMESTAMP)", chunk_rows)
    return len(chunk_rows)


def _persist_term_stats(con, provider, texts: list[str]) -> None:
    import math
    from collections import Counter

    tokenise = getattr(provider, "_tokens", None)
    if tokenise is None:                       # cloud providers need no term stats
        return
    n_docs = max(1, len(texts))
    df = Counter()
    for text in texts:
        df.update(set(tokenise(text)))
    rows = [[term, freq, round(math.log((n_docs + 1) / (freq + 1)) + 1.0, 6), n_docs]
            for term, freq in df.items()]
    con.execute("DELETE FROM ACME_EDP.AI.KB_TERM_STATS")
    con.executemany(
        "INSERT INTO ACME_EDP.AI.KB_TERM_STATS (TERM, DOC_FREQ, IDF, N_DOCS, COMPUTED_AT)"
        " VALUES (?,?,?,?, CURRENT_TIMESTAMP)", rows)
    provider.load_idf({r[0]: r[2] for r in rows}, default=math.log(n_docs + 1) + 1.0)


def _load_term_stats(con, provider) -> None:
    import math
    if not hasattr(provider, "load_idf"):
        return
    rows = con.execute("SELECT TERM, IDF, N_DOCS FROM ACME_EDP.AI.KB_TERM_STATS").fetchall()
    if rows:
        provider.load_idf({t: float(i) for t, i, _ in rows},
                          default=math.log(float(rows[0][2]) + 1.0) + 1.0)


# Vector search runs *in the warehouse*, not in the service.
#
# Local:  DuckDB   list_cosine_similarity(EMBEDDING, CAST(? AS DOUBLE[]))
# Cloud:  Snowflake VECTOR_COSINE_SIMILARITY(EMBEDDING, ?::VECTOR(FLOAT, 768))
#
# Same shape, same semantics, and in both cases the corpus never leaves the data
# platform - only the query vector goes in and the top-k chunks come out.  See
# snowflake/08-ai/04-rag-vector-search.sql for the Snowflake statement.
VECTOR_SEARCH_SQL = """
SELECT c.CHUNK_ID, c.ARTICLE_ID, d.TITLE, c.CHUNK_TEXT,
       list_cosine_similarity(c.EMBEDDING, CAST(? AS DOUBLE[])) AS SIMILARITY
FROM ACME_EDP.AI.KB_CHUNK c
JOIN ACME_EDP.AI.KB_DOCUMENT d ON d.DOCUMENT_ID = c.DOCUMENT_ID
WHERE d.IS_ACTIVE = TRUE
ORDER BY SIMILARITY DESC
LIMIT ?
"""

TERM_STATS_SQL = "SELECT TERM, IDF, N_DOCS FROM ACME_EDP.AI.KB_TERM_STATS"


async def retrieve(query: str, top_k: int = DEFAULT_TOP_K,
                   floor: float = SIMILARITY_FLOOR) -> list[RetrievedChunk]:
    import math

    from common import data_platform  # noqa: PLC0415

    from .providers import build_provider  # noqa: PLC0415

    provider = build_provider()
    if hasattr(provider, "load_idf"):
        stats = await data_platform.query(TERM_STATS_SQL)
        if stats:
            provider.load_idf({r["TERM"]: float(r["IDF"]) for r in stats},
                              default=math.log(float(stats[0]["N_DOCS"]) + 1.0) + 1.0)

    qvec = (await provider.embed([query]))[0]
    rows = await data_platform.query(
        VECTOR_SEARCH_SQL, "[" + ",".join(f"{v:.8f}" for v in qvec) + "]", top_k)

    # The floor is what allows retrieval to return nothing.  Without it every
    # question, however unrelated, gets k confident-looking extracts and the
    # model answers from them.
    return [RetrievedChunk(r["CHUNK_ID"], r["ARTICLE_ID"], r["TITLE"], r["CHUNK_TEXT"],
                           float(r["SIMILARITY"]))
            for r in rows if float(r["SIMILARITY"]) >= floor]


def format_context(chunks: list[RetrievedChunk]) -> str:
    if not chunks:
        return "(no relevant knowledge-base extracts were retrieved)"
    return "\n\n".join(
        f"[{c.article_id}] {c.title} (relevance {c.score:.2f})\n{c.text}" for c in chunks)
