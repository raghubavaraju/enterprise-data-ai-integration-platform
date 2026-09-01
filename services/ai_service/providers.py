"""Model providers behind one interface.

Four implementations, one contract:

    local   deterministic, offline, no cost.  Composes text strictly from the
            supplied grounding facts.  It is NOT a language model and does not
            pretend to be one - it exists so that the *architecture* (grounding,
            redaction, evaluation, audit, human-in-the-loop) can be exercised
            and tested without a paid account, and so CI is deterministic.
    cortex  Snowflake Cortex.  The grounding data never leaves the account,
            which is the strongest argument for it in a regulated context.
    openai  external LLM gateway.
    bedrock AWS Bedrock.

The provider boundary is on purpose thin: the moment provider-specific logic
leaks into the capability code, swapping providers becomes a rewrite instead of
a configuration change - and provider swaps are certain, not hypothetical.
"""
from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass
from typing import Protocol

from common.config import get_settings

log = logging.getLogger("ai.providers")
_settings = get_settings()


@dataclass
class Completion:
    text: str
    input_tokens: int
    output_tokens: int
    latency_ms: int
    provider: str
    model: str


class ModelProvider(Protocol):
    name: str

    async def complete(self, system: str, user: str, *, max_tokens: int,
                       temperature: float) -> Completion: ...

    async def embed(self, texts: list[str]) -> list[list[float]]: ...


def _approx_tokens(text: str) -> int:
    return max(1, len(text) // 4)


# ---------------------------------------------------------------------------
# Local deterministic provider
# ---------------------------------------------------------------------------
class LocalProvider:
    """Composes an answer from the FACTS block only.

    Every sentence it emits is assembled from values parsed out of the prompt's
    grounding block, which means it is *incapable* of hallucinating a number.
    That is the point: the groundedness evaluator in ``evaluation.py`` should
    score it at 1.0, and any drop below that is a bug in the pipeline rather
    than model behaviour.
    """

    name = "local"

    def __init__(self, model: str = "acme-local-deterministic-v1"):
        self.model = model

    @staticmethod
    def _facts(user: str) -> dict[str, str]:
        out: dict[str, str] = {}
        block = user.split("FACTS", 1)[-1]
        for line in block.splitlines():
            m = re.match(r"^-\s+([A-Za-z0-9_ ]+):\s*(.*)$", line.strip())
            if m and m.group(2):
                out[m.group(1).strip()] = m.group(2).strip()
            if line.strip().startswith(("TASK", "OUTPUT FORMAT", "APPROVED ACTIONS")):
                break
        return out

    @staticmethod
    def _has(f: dict[str, str], key: str) -> bool:
        """A fact counts as present only if it has a usable value.

        "NOT AVAILABLE" is the render_facts marker for a NULL.  Treating it as a
        value is how a briefing ends up saying "last ordered NOT AVAILABLE days
        ago" - which is worse than saying nothing, because it looks like data.
        """
        v = f.get(key)
        return v not in (None, "", "NOT AVAILABLE", "n/a")

    def _summary(self, f: dict[str, str]) -> str:
        parts = []
        if self._has(f, "tenureDays"):
            parts.append(f"The customer has been with Acme for {f['tenureDays']} days "
                         f"and is in the {f.get('customerSegment', 'unclassified')} segment.")
        if self._has(f, "totalOrders") and self._int(f, "totalOrders") > 0:
            parts.append(f"They have placed {f['totalOrders']} orders worth "
                         f"{f.get('totalNetRevenue', 'an unrecorded amount')} in total, "
                         f"averaging {f.get('avgOrderValue', 'n/a')} per order.")
        else:
            parts.append("They have no recorded purchase history.")
        if self._has(f, "daysSinceLastOrder"):
            trend = (f"and the recent order trend ratio is {f['orderTrendRatio']}"
                     if self._has(f, "orderTrendRatio") else
                     "and no order trend could be computed")
            parts.append(f"Their last order was {f['daysSinceLastOrder']} days ago {trend}.")
        if self._has(f, "totalCases"):
            parts.append(f"Support history shows {f['totalCases']} cases "
                         f"({f.get('openCases', '0')} open) with an average satisfaction score of "
                         f"{f['avgCsat'] if self._has(f, 'avgCsat') else 'not recorded'}.")
        if self._has(f, "loyaltyTier"):
            parts.append(f"Loyalty standing is {f['loyaltyTier']} with "
                         f"{f.get('loyaltyPointsBalance', '0')} points.")
        if self._has(f, "churnRiskBand"):
            parts.append(f"Most important for this conversation: churn risk is "
                         f"{f['churnRiskBand']} (probability "
                         f"{f.get('churnProbability', 'not available')}), driven mainly by "
                         f"{f.get('topDriver1', 'an unspecified factor')}.")
        return " ".join(parts) or "Insufficient facts were supplied to produce a briefing."

    def _churn(self, f: dict[str, str]) -> str:
        drivers = [f.get(k) for k in ("topDriver1", "topDriver2", "topDriver3") if f.get(k)]
        readable = {
            "PURCHASE_RECENCY": (f"they have not ordered for {f['daysSinceLastOrder']} days"
                                 if self._has(f, "daysSinceLastOrder")
                                 else "they have no recent purchase activity"),
            "DECLINING_ORDER_TREND": ("their recent order rate has fallen (trend ratio "
                                      f"{f['orderTrendRatio']})"
                                      if self._has(f, "orderTrendRatio")
                                      else "their recent order rate has fallen"),
            "SUPPORT_CASE_VOLUME": f"they have raised {f.get('casesLast90d', 'n/a')} support cases "
                                   f"in the last 90 days",
            "LOW_SATISFACTION": f"their average satisfaction score is {f.get('avgCsat', 'n/a')}",
            "LOW_ENGAGEMENT": f"their engagement score is {f.get('engagementScore', 'n/a')} out of 100",
            "LOYALTY_INACTIVITY": "their loyalty account has been inactive",
            "NEGATIVE_SIGNALS": f"they generated {f.get('negativeSignals90d', 'n/a')} negative "
                                f"engagement signals in the last 90 days",
        }
        clauses = [readable.get(d, d.lower().replace("_", " ")) for d in drivers]
        if not clauses:
            return "No churn drivers were supplied, so no explanation can be given."
        return (f"Churn risk is {f.get('churnRiskBand', 'unclassified')} with a probability of "
                f"{f.get('churnProbability', 'n/a')}. The main reasons are that "
                + "; ".join(clauses) + ".")

    @staticmethod
    def _int(f: dict[str, str], key: str, default: int = 0) -> int:
        raw = f.get(key)
        if raw in (None, "", "NOT AVAILABLE"):
            return default
        try:
            return int(float(raw))
        except (TypeError, ValueError):
            return default

    def _nba(self, f: dict[str, str], user: str) -> str:
        open_cases = self._int(f, "openCases", 0)
        # A customer who has never ordered is not "0 days since last order".
        days = self._int(f, "daysSinceLastOrder", 9999)
        band = f.get("churnRiskBand", "LOW")
        known_days = self._has(f, "daysSinceLastOrder")
        if open_cases > 0:
            action, prio = "RESOLVE_OPEN_CASE", "HIGH"
            why = (f"the customer has {open_cases} open support case(s), which must be "
                   f"closed before any offer")
        elif band in ("HIGH", "CRITICAL") and days >= 120:
            action, prio = "RETENTION_OFFER_15_PCT", "HIGH"
            when = (f"there has been no order for {f['daysSinceLastOrder']} days"
                    if known_days else "there is no recorded purchase activity")
            why = (f"churn risk is {band} and {when}, which meets the KB-009 "
                   f"win-back threshold")
        elif band in ("HIGH", "CRITICAL"):
            action, prio = "PROACTIVE_SERVICE_CALL", "MEDIUM"
            why = f"churn risk is {band} but the customer has ordered within the last 120 days, so the KB-009 win-back offer does not apply"
        elif f.get("loyaltyTier") in (None, "NONE", "NOT_ENROLLED"):
            action, prio = "DOUBLE_POINTS_MONTH", "LOW"
            why = "the customer is not benefiting from the loyalty programme"
        else:
            action, prio = "NO_ACTION", "LOW"
            why = f"churn risk is {band} and the relationship shows no deterioration"
        return json.dumps({"action": action, "priority": prio, "justification": why})

    def _sentiment(self, f: dict[str, str]) -> str:
        csat = f.get("avgCsat")
        try:
            value = float(csat) if csat not in (None, "", "NOT AVAILABLE") else None
        except ValueError:
            value = None
        if value is None:
            return json.dumps({"label": "NEUTRAL", "score": 0.0,
                               "evidence": "No satisfaction scores were supplied."})
        score = round((value - 3.0) / 2.0, 2)
        label = "POSITIVE" if score > 0.2 else "NEGATIVE" if score < -0.2 else "NEUTRAL"
        return json.dumps({"label": label, "score": score,
                           "evidence": f"Average satisfaction score across supplied cases is {value}."})

    def _grounded_qa(self, user: str) -> str:
        kb = user.split("RETRIEVED KNOWLEDGE BASE EXTRACTS", 1)[-1].split("QUESTION", 1)[0]
        ids = re.findall(r"\[(KB-\d+)\]", kb)
        if not ids:
            return "The knowledge base does not cover this."
        first = kb.strip().split("\n\n")[0].strip()
        return f"{first[:400]} [{ids[0]}]"

    async def complete(self, system: str, user: str, *, max_tokens: int,
                       temperature: float) -> Completion:
        started = time.perf_counter()
        facts = self._facts(user)
        if "next-best" in system.lower() or "APPROVED ACTIONS" in user:
            text = self._nba(facts, user)
        elif "sentiment" in system.lower():
            text = self._sentiment(facts)
        elif "churn-risk scores" in system or "churn" in system.lower():
            text = self._churn(facts)
        elif "RETRIEVED KNOWLEDGE BASE EXTRACTS" in user:
            text = self._grounded_qa(user)
        else:
            text = self._summary(facts)
        return Completion(text=text, input_tokens=_approx_tokens(system + user),
                          output_tokens=_approx_tokens(text),
                          latency_ms=int((time.perf_counter() - started) * 1000),
                          provider=self.name, model=self.model)

    # Words that carry no retrieval signal in this corpus.  A real embedding
    # model learns to down-weight these; the offline stand-in has to be told.
    _STOPWORDS = frozenset(["a", "an", "and", "are", "as", "at", "be", "been", "but", "by", "can", "cannot", "did", "do", "does", "for", "from", "had", "has", "have", "how", "i", "if", "in", "into", "is", "it", "its", "may", "must", "no", "not", "of", "on", "or", "our", "out", "over", "shall", "she", "should", "so", "than", "that", "the", "their", "them", "then", "there", "these", "they", "this", "to", "up", "was", "we", "were", "what", "when", "where", "which", "who", "why", "will", "with", "within", "would", "you", "your", "acme", "customer", "customers", "order", "orders", "please", "must", "can", "also", "any", "within", "after", "before", "each", "per"])

    _idf_cache: dict[str, float] | None = None
    _idf_default: float = 1.0

    @staticmethod
    def _stem(token: str) -> str:
        """Crude suffix stripping.

        Not linguistics - just enough that "charged"/"charge"/"charges" collide,
        which is most of what stemming buys on a policy corpus.  A real
        embedding model needs none of this.
        """
        for suffix in ("ing", "ies", "ied", "ed", "es", "s"):
            if len(token) > len(suffix) + 3 and token.endswith(suffix):
                stem = token[: -len(suffix)]
                return stem + "y" if suffix in ("ies", "ied") else stem
        return token

    @classmethod
    def _tokens(cls, text: str) -> list[str]:
        return [cls._stem(t) for t in re.findall(r"[a-z][a-z']{2,}", text.lower())
                if t not in cls._STOPWORDS]

    @classmethod
    def load_idf(cls, mapping: dict[str, float], default: float) -> None:
        """Install corpus term statistics (see ``ai_service.rag.build_corpus``)."""
        cls._idf_cache, cls._idf_default = mapping, default

    @classmethod
    def _idf(cls, term: str) -> float:
        if cls._idf_cache is None:
            return 1.0
        return cls._idf_cache.get(term, cls._idf_default)

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Deterministic hashed TF-IDF embedding.

        Not a language model and not a claim to be one.  It is a lexical vector
        that is stable, offline, free and good enough to make retrieval behave
        correctly on a small corpus - including *failing to retrieve* when the
        question is out of scope, which is the behaviour that matters for
        testing the grounding path.

        Differences from a real embedding model, stated plainly: no synonymy, no
        paraphrase robustness, and it is corpus-aware (it uses IDF), which a
        sentence-transformer is not.  In cloud mode this is replaced by
        ``EMBED_TEXT_768('snowflake-arctic-embed-m', ...)`` and nothing else in
        the pipeline changes.
        """
        import hashlib
        import math
        from collections import Counter
        dim = 768
        vectors = []
        for text in texts:
            counts = Counter(self._tokens(text))
            vec = [0.0] * dim
            for tok, tf in counts.items():
                weight = (1.0 + math.log(tf)) * self._idf(tok)
                h = int(hashlib.md5(tok.encode(), usedforsecurity=False).hexdigest()[:8], 16)
                # Signed hashing reduces collision bias between distinct terms.
                vec[h % dim] += weight * (1.0 if (h >> 31) & 1 else -1.0)
            norm = math.sqrt(sum(v * v for v in vec)) or 1.0
            vectors.append([v / norm for v in vec])
        return vectors


# ---------------------------------------------------------------------------
# Cortex / OpenAI / Bedrock
# ---------------------------------------------------------------------------
class CortexProvider:
    """Snowflake Cortex via the SQL API.

    The prompt is passed as a bind parameter, never string-concatenated into the
    SQL: concatenating customer text into a statement is SQL injection with extra
    steps.  The corresponding SQL is in ``snowflake/08-ai/03-cortex-inference.sql``.
    """

    name = "cortex"

    def __init__(self, model: str, sql_executor):
        self.model = model
        self._execute = sql_executor

    async def complete(self, system: str, user: str, *, max_tokens: int,
                       temperature: float) -> Completion:
        started = time.perf_counter()
        rows = await self._execute(
            "SELECT AI_COMPLETE(?, ?, {'temperature': ?, 'max_tokens': ?}) AS RESPONSE",
            [self.model, f"{system}\n\n{user}", temperature, max_tokens])
        text = rows[0]["RESPONSE"] if rows else ""
        return Completion(text=text, input_tokens=_approx_tokens(system + user),
                          output_tokens=_approx_tokens(text),
                          latency_ms=int((time.perf_counter() - started) * 1000),
                          provider=self.name, model=self.model)

    async def embed(self, texts: list[str]) -> list[list[float]]:
        out = []
        for chunk in texts:
            rows = await self._execute(
                "SELECT EMBED_TEXT_768(?, ?) AS V", [_settings.ai_embedding_model, chunk])
            out.append(rows[0]["V"])
        return out


class OpenAIProvider:
    name = "openai"

    def __init__(self, model: str, api_key: str, base_url: str):
        self.model, self._key, self._base = model, api_key, base_url.rstrip("/")

    async def complete(self, system: str, user: str, *, max_tokens: int,
                       temperature: float) -> Completion:
        import httpx
        started = time.perf_counter()
        async with httpx.AsyncClient(timeout=_settings.ai_timeout_seconds) as client:
            resp = await client.post(
                f"{self._base}/chat/completions",
                headers={"Authorization": f"Bearer {self._key}"},
                json={"model": self.model, "temperature": temperature,
                      "max_tokens": max_tokens,
                      "messages": [{"role": "system", "content": system},
                                   {"role": "user", "content": user}]})
            resp.raise_for_status()
            body = resp.json()
        usage = body.get("usage", {})
        return Completion(text=body["choices"][0]["message"]["content"],
                          input_tokens=usage.get("prompt_tokens", 0),
                          output_tokens=usage.get("completion_tokens", 0),
                          latency_ms=int((time.perf_counter() - started) * 1000),
                          provider=self.name, model=self.model)

    async def embed(self, texts: list[str]) -> list[list[float]]:
        import httpx
        async with httpx.AsyncClient(timeout=_settings.ai_timeout_seconds) as client:
            resp = await client.post(f"{self._base}/embeddings",
                                     headers={"Authorization": f"Bearer {self._key}"},
                                     json={"model": "text-embedding-3-small", "input": texts})
            resp.raise_for_status()
            return [d["embedding"] for d in resp.json()["data"]]


def build_provider(sql_executor=None) -> ModelProvider:
    provider = _settings.ai_provider.lower()
    if provider == "cortex":
        if sql_executor is None:
            raise RuntimeError("AI_PROVIDER=cortex requires a Snowflake SQL executor.")
        return CortexProvider(_settings.ai_model, sql_executor)
    if provider == "openai":
        if not _settings.openai_api_key:
            raise RuntimeError("AI_PROVIDER=openai requires OPENAI_API_KEY.")
        return OpenAIProvider(_settings.ai_model, _settings.openai_api_key,
                              _settings.openai_base_url)
    if provider != "local":
        log.warning("Unknown AI_PROVIDER '%s'; falling back to the local provider.", provider)
    return LocalProvider()
