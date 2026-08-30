"""Snowflake -> DuckDB dialect rewriting for the local warehouse.

Philosophy: keep the rewrite list *small, explicit and auditable*.  Every rule
below is a real, named difference between the two engines.  If a script needs a
rule that is not here, the right answer is to mark the script Snowflake-only
rather than to grow a general-purpose SQL translator - a half-working translator
is worse than an honest boundary, because it produces subtly different results
instead of an error.
"""
from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# Constructs that have no DuckDB equivalent.  A script containing any of these
# is Snowflake-only and is skipped with the reason reported.
# ---------------------------------------------------------------------------
# TODO: the MERGE entry is version-pinned in the message. DuckDB gained a
# limited MERGE later; check the installed version before assuming.
UNPORTABLE: dict[str, str] = {
    r"\bCREATE\s+(OR\s+REPLACE\s+)?(PIPE|STREAM|TASK)\b": "Snowpipe / streams / tasks",
    r"\bMERGE\s+INTO\b": "MERGE (not available in DuckDB 1.1)",
    r"\bSNOWFLAKE\.CORTEX\.": "Cortex LLM functions",
    r"\bAI_COMPLETE\s*\(": "Cortex AI_COMPLETE",
    r"\bEMBED_TEXT_768\s*\(": "Cortex embeddings",
    r"\bVECTOR_COSINE_SIMILARITY\s*\(": "Snowflake VECTOR type + similarity",
    r"\bCREATE\s+(OR\s+REPLACE\s+)?MASKING\s+POLICY\b": "dynamic data masking policy",
    r"\bCREATE\s+(OR\s+REPLACE\s+)?ROW\s+ACCESS\s+POLICY\b": "row access policy",
    r"\bCREATE\s+(OR\s+REPLACE\s+)?(WAREHOUSE|RESOURCE\s+MONITOR|STAGE|FILE\s+FORMAT)\b":
        "account-level object (warehouse / monitor / stage / file format)",
    r"\bCREATE\s+(OR\s+REPLACE\s+)?(PROCEDURE|FUNCTION)\b": "Snowflake Scripting procedure",
    r"\bGRANT\b|\bCREATE\s+ROLE\b": "RBAC grants",
    r"\bCOPY\s+INTO\b": "COPY INTO from a stage",
    r"\bAT\s*\(\s*(TIMESTAMP|OFFSET|STATEMENT)": "Time Travel",
}

# ---------------------------------------------------------------------------
# Mechanical rewrites.  Order matters.
# ---------------------------------------------------------------------------
REWRITES: list[tuple[str, str, str]] = [
    # -- statements that are meaningless outside Snowflake --------------------
    (r"(?im)^\s*USE\s+(DATABASE|SCHEMA|WAREHOUSE|ROLE)\s+[^;]+;\s*$", "",
     "USE statements: portable scripts fully qualify every object instead"),
    (r"(?is)\bCOMMENT\s*=\s*'(?:[^']|'')*'(\s*'(?:[^']|'')*')*", "",
     "object COMMENT clauses (DuckDB has no DDL comment syntax)"),
    (r"(?i)\bCONSTRAINT\s+\w+\s+PRIMARY\s+KEY\s*\([^)]*\)\s*,?", "",
     "declared-but-not-enforced PK: DuckDB would enforce it, changing behaviour"),
    (r"(?i)\bCLUSTER\s+BY\s*\([^)]*\)", "", "CLUSTER BY (micro-partition pruning hint)"),
    (r"(?i)\bDATA_RETENTION_TIME_IN_DAYS\s*=\s*\d+", "", "Time Travel retention"),

    # -- types ---------------------------------------------------------------
    (r"(?i)\bNUMBER\s*\(", "DECIMAL(", "NUMBER(p,s) -> DECIMAL(p,s)"),
    (r"(?i)\bTIMESTAMP_NTZ\b", "TIMESTAMP", "TIMESTAMP_NTZ -> TIMESTAMP"),
    (r"(?i)\bTIMESTAMP_LTZ\b|\bTIMESTAMP_TZ\b", "TIMESTAMPTZ", "TIMESTAMP_LTZ/TZ -> TIMESTAMPTZ"),
    (r"(?i)\bVARIANT\b", "JSON", "VARIANT -> JSON"),
    (r"(?i)\bSTRING\b", "VARCHAR", "STRING -> VARCHAR"),
    (r"(?i)\bVECTOR\s*\(\s*FLOAT\s*,\s*\d+\s*\)", "DOUBLE[]",
     "VECTOR(FLOAT, n) -> DOUBLE[] (cosine similarity done in Python locally)"),
    # VARCHAR(16777216) is Snowflake's max; DuckDB ignores the length but the
    # literal is large enough to trip its parser in some builds.
    (r"(?i)\bVARCHAR\s*\(\s*16777216\s*\)", "VARCHAR", "unbounded VARCHAR"),

    # -- functions -----------------------------------------------------------
    (r"(?i)\bCURRENT_TIMESTAMP\s*\(\s*\)", "CURRENT_TIMESTAMP", "CURRENT_TIMESTAMP()"),
    (r"(?i)\bCURRENT_DATE\s*\(\s*\)", "CURRENT_DATE", "CURRENT_DATE()"),
    (r"(?i)\bREGEXP_LIKE\s*\(", "regexp_matches(", "REGEXP_LIKE -> regexp_matches"),
    (r"(?i)\bDATEDIFF\s*\(\s*(year|quarter|month|week|day|hour|minute|second)\s*,",
     r"date_diff('\1',", "DATEDIFF(part, ...) -> date_diff('part', ...)"),
    (r"(?i)\bLISTAGG\s*\(", "string_agg(", "LISTAGG -> string_agg"),
    (r"(?i)\bOBJECT_CONSTRUCT\s*\(", "json_object(", "OBJECT_CONSTRUCT -> json_object"),
    (r"(?i)\bPARSE_JSON\s*\(", "json(", "PARSE_JSON -> json"),
    (r"(?i)\bZEROIFNULL\s*\(", "COALESCE0__(", "ZEROIFNULL -> COALESCE(x, 0)"),
]

# NULLS LAST / NULLS FIRST are supported by both, and QUALIFY, TRY_CAST,
# GREATEST/LEAST, MODE() and window functions behave the same way, so they are
# deliberately absent from this list.


def unportable_reason(sql: str) -> str | None:
    stripped = _strip_comments(sql)
    for pattern, reason in UNPORTABLE.items():
        if re.search(pattern, stripped, re.IGNORECASE):
            return reason
    return None


def _strip_comments(sql: str) -> str:
    sql = re.sub(r"/\*.*?\*/", " ", sql, flags=re.DOTALL)
    sql = re.sub(r"--[^\n]*", " ", sql)
    return sql


def translate(sql: str) -> str:
    """Apply the rewrite rules to one script."""
    out = sql
    for pattern, replacement, _reason in REWRITES:
        out = re.sub(pattern, replacement, out)
    # ZEROIFNULL needs a second argument; handled after the marker substitution.
    out = re.sub(r"COALESCE0__\(([^()]*)\)", r"COALESCE(\1, 0)", out)
    # Snowflake tolerates a trailing comma left by a removed CONSTRAINT clause.
    out = re.sub(r",\s*\)", "\n)", out)
    return out


def split_statements(sql: str) -> list[str]:
    """Split on semicolons that are outside string literals and comments.

    Handles SQL's doubled-quote escape (``'it''s'``), which is why this is a
    scanner and not a ``sql.split(";")``.
    """
    statements, buf = [], []
    in_str = False
    i, n = 0, len(sql)
    while i < n:
        ch = sql[i]
        if not in_str:
            if sql.startswith("--", i):
                j = sql.find("\n", i)
                i = n if j == -1 else j
                continue
            if sql.startswith("/*", i):
                j = sql.find("*/", i)
                i = n if j == -1 else j + 2
                continue
            if ch == "'":
                in_str = True
                buf.append(ch)
                i += 1
                continue
            if ch == ";":
                stmt = "".join(buf).strip()
                if stmt:
                    statements.append(stmt)
                buf = []
                i += 1
                continue
            buf.append(ch)
            i += 1
            continue
        # inside a string literal
        if ch == "'":
            if i + 1 < n and sql[i + 1] == "'":
                buf.append("''")
                i += 2
                continue
            in_str = False
        buf.append(ch)
        i += 1
    tail = "".join(buf).strip()
    if tail:
        statements.append(tail)
    return statements


def rule_documentation() -> list[dict[str, str]]:
    """Used by docs generation and by tests/data/test_dialect_rules.py."""
    return ([{"kind": "rewrite", "pattern": p, "note": note} for p, _r, note in REWRITES]
            + [{"kind": "skip", "pattern": p, "note": r} for p, r in UNPORTABLE.items()])
