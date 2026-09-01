"""Access to the analytical data platform.

Two access modes behind one interface:

    direct  in-process access to the local DuckDB warehouse.  Used by the build,
            by the tests, and by the data API itself.
    api     over the Snowflake SQL API contract (HTTP).  Used by every other
            service.

Why the AI service goes through the API instead of opening the warehouse
itself, in both modes:

  * Local: DuckDB permits exactly one read-write process.  Two services opening
    the file is not a design choice, it is a crash.
  * Cloud: it keeps the AI service's data access *narrow and named*.  It cannot
    execute arbitrary SQL against Snowflake; it can read the AI-safe views and
    it can invoke three named, parameterised write operations.  A service that
    can run arbitrary SQL is one prompt-injection bug away from being a data
    exfiltration tool.

The named-write list is intentionally short and lives in ``WRITE_OPERATIONS``.
Adding to it is a reviewable change, which is the idea.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any

from .config import get_settings
from .errors import DataPlatformError

log = logging.getLogger("data_platform")
_settings = get_settings()


def access_mode() -> str:
    return os.getenv("WAREHOUSE_ACCESS", "api").lower()


# ---------------------------------------------------------------------------
# Named write operations.  Every one is a fixed statement with bind parameters.
# ---------------------------------------------------------------------------
WRITE_OPERATIONS: dict[str, str] = {
    "ai_insight": """
        INSERT INTO ACME_EDP.AI.AI_CUSTOMER_INSIGHTS (
            INSIGHT_ID, CUSTOMER_BK, INSIGHT_TYPE, GENERATED_TEXT, RECOMMENDED_ACTION,
            ACTION_PRIORITY, SENTIMENT_LABEL, SENTIMENT_SCORE, GROUNDING_SNAPSHOT,
            GROUNDING_SOURCE_IDS, PROMPT_TEMPLATE_ID, PROMPT_VERSION, MODEL_PROVIDER,
            MODEL_NAME, MODEL_TEMPERATURE, INPUT_TOKENS, OUTPUT_TOKENS, LATENCY_MS,
            CONFIDENCE_SCORE, GROUNDEDNESS_SCORE, REVIEW_STATUS, IS_PII_REDACTED,
            GENERATED_AT, EXPIRES_AT, _CORRELATION_ID)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """,
    "ai_audit": """
        INSERT INTO ACME_EDP.AI.AI_REQUEST_AUDIT (
            REQUEST_ID, CORRELATION_ID, CUSTOMER_BK, REQUESTED_BY_CLIENT_ID,
            REQUESTED_BY_SUBJECT, CAPABILITY, PROMPT_TEMPLATE_ID, PROMPT_VERSION,
            MODEL_PROVIDER, MODEL_NAME, INPUT_TOKENS, OUTPUT_TOKENS, ESTIMATED_COST_USD,
            LATENCY_MS, OUTCOME, BLOCK_REASON, PII_REDACTION_APPLIED, REQUESTED_AT)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """,
    "ai_evaluation": """
        INSERT INTO ACME_EDP.AI.AI_EVALUATION_RESULT (
            EVALUATION_ID, EVALUATION_RUN_ID, INSIGHT_ID, TEST_CASE_ID, METRIC_NAME,
            METRIC_SCORE, THRESHOLD, PASSED, EVALUATOR, NOTES, EVALUATED_AT)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)
    """,
}


def _direct_connection():
    from local_warehouse.warehouse import shared  # noqa: PLC0415
    return shared()


async def query(sql: str, *params: Any) -> list[dict]:
    if access_mode() == "direct":
        con = _direct_connection()
        try:
            cur = con.execute(sql, list(params))
        except Exception as exc:                           # noqa: BLE001
            raise DataPlatformError(f"Query execution failed: {exc}") from exc
        columns = [d[0] for d in cur.description or []]
        return [dict(zip(columns, row, strict=True)) for row in cur.fetchall()]

    from .http_client import DownstreamClient  # noqa: PLC0415
    from .security import issue_token  # noqa: PLC0415
    client = DownstreamClient("snowflake-sql-api", _settings.snowflake_data_api_url)
    token = issue_token("acme-ai-service", _settings.oauth_client_secret,
                        "customer:read insights:read")["access_token"]
    types = {str: "TEXT", int: "FIXED", float: "REAL", bool: "BOOLEAN"}
    body = await client.post("/api/v2/statements", json={
        "statement": sql,
        "bindings": {str(i + 1): {"type": types.get(type(v), "TEXT"), "value": v}
                     for i, v in enumerate(params)},
        "timeout": 30,
    }, headers={"Authorization": f"Bearer {token}"})
    meta = body.get("resultSetMetaData", {}).get("rowType", [])
    names = [c["name"] for c in meta]
    kinds = [c["type"] for c in meta]
    rows = []
    for raw in body.get("data", []):
        rows.append({name: _coerce(value, kind)
                     for name, kind, value in zip(names, kinds, raw, strict=True)})
    return rows


def _coerce(raw, kind: str):
    if raw is None:
        return None
    if kind == "FIXED":
        try:
            return int(float(raw))
        except (TypeError, ValueError):
            return raw
    if kind == "REAL":
        try:
            return float(raw)
        except (TypeError, ValueError):
            return raw
    if kind == "BOOLEAN":
        return str(raw).lower() in ("true", "1", "t")
    return raw


async def write(operation: str, rows: list[list[Any]]) -> int:
    if operation not in WRITE_OPERATIONS:
        raise DataPlatformError(f"'{operation}' is not an approved write operation.")
    if not rows:
        return 0
    if access_mode() == "direct":
        con = _direct_connection()
        con.executemany(WRITE_OPERATIONS[operation], rows)
        return len(rows)

    from .http_client import DownstreamClient  # noqa: PLC0415
    from .security import issue_token  # noqa: PLC0415
    client = DownstreamClient("snowflake-sql-api", _settings.snowflake_data_api_url)
    token = issue_token("acme-ai-service", _settings.oauth_client_secret,
                        "ai:write")["access_token"]
    body = await client.post(f"/internal/v1/writes/{operation}",
                             json={"rows": json.loads(json.dumps(rows, default=str))},
                             headers={"Authorization": f"Bearer {token}"})
    return body.get("rowsWritten", 0)
