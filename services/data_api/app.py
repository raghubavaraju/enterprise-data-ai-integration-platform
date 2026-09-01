"""Snowflake SQL API - local implementation.

This service exists to make one architectural claim testable: the MuleSoft
Snowflake System API should talk to Snowflake over its **SQL API** (HTTPS +
OAuth/key-pair JWT), not over a JDBC connection pool.

Why that matters, and why it is worth a service:

  * CloudHub workers are ephemeral and horizontally scaled.  A JDBC pool per
    worker multiplies idle Snowflake sessions by the worker count and makes
    warehouse auto-suspend far less effective - you pay for a warehouse kept
    warm by connections nobody is using.
  * The HTTP Request connector gives you the platform's own retry, timeout,
    circuit-breaker and correlation-id behaviour for free.  A JDBC call is
    opaque to all of it.
  * Statements can be submitted asynchronously and polled, which is the only
    sane way for an integration platform to run a query that might take minutes.

Because the contract is HTTP, local mode can implement the same contract over
DuckDB.  The Mule flow's HTTP request configuration changes host and credential
between environments - not logic.

Implemented subset of the real API:
    POST /api/v2/statements                submit (sync or async)
    GET  /api/v2/statements/{handle}       poll an async statement
    POST /api/v2/statements/{handle}/cancel
The response envelope mirrors Snowflake's: ``resultSetMetaData.rowType`` plus
``data`` as an array of arrays of strings.  Deliberate, so the DataWeave that
parses it is the same in both modes.
"""
from __future__ import annotations

import re
import threading
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from fastapi import Depends, FastAPI, Request
from pydantic import BaseModel, Field

from common.config import get_settings
from common.errors import (
    DataPlatformError,
    PlatformError,
    ValidationError,
    platform_error_handler,
    unhandled_error_handler,
)
from common.logging_config import configure_logging
from common.middleware import (
    CorrelationIdMiddleware,
    RateLimitMiddleware,
    SecurityHeadersMiddleware,
    current_correlation_id,
)
from common.security import require_scopes

_settings = get_settings()
configure_logging("snowflake-data-api", _settings.log_level, _settings.log_format)

app = FastAPI(title="Snowflake SQL API (local implementation)", version="2.0.0")
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(RateLimitMiddleware)
app.add_middleware(CorrelationIdMiddleware)
app.add_exception_handler(PlatformError, platform_error_handler)
app.add_exception_handler(Exception, unhandled_error_handler)

_ASYNC_RESULTS: dict[str, dict] = {}
_LOCK = threading.Lock()

# ---------------------------------------------------------------------------
# Guardrails on what may be executed.
#
# The System API's Snowflake credential is read-only by RBAC (see
# snowflake/10-security), and this is the second line of defence: even a
# compromised caller cannot get a mutating statement past the API.  Defence in
# depth is the point - either control alone would be a single point of failure.
# ---------------------------------------------------------------------------
_FORBIDDEN = re.compile(
    r"\b(INSERT|UPDATE|DELETE|MERGE|DROP|ALTER|CREATE|TRUNCATE|GRANT|REVOKE|COPY|CALL|"
    r"EXECUTE|PUT|REMOVE)\b", re.IGNORECASE)
_ALLOWED_PREFIX = re.compile(r"^\s*(WITH|SELECT)\b", re.IGNORECASE)


class StatementRequest(BaseModel):
    statement: str = Field(min_length=1, max_length=20000)
    # Bind parameters, Snowflake style: {"1": {"type": "TEXT", "value": "CRM-100001"}}
    bindings: dict[str, dict[str, Any]] | None = None
    timeout: int = Field(default=30, ge=1, le=300)
    database: str | None = None
    schema_: str | None = Field(default=None, alias="schema")
    warehouse: str | None = None
    role: str | None = None
    asyncExec: bool = Field(default=False, alias="async")

    model_config = {"populate_by_name": True}


def _validate(statement: str) -> None:
    if not _ALLOWED_PREFIX.match(statement):
        raise ValidationError("Only SELECT and WITH statements are accepted by this API.")
    # Reject statement batching outright: one call, one statement.
    if ";" in statement.rstrip().rstrip(";"):
        raise ValidationError("Multiple statements in a single request are not permitted.")
    if _FORBIDDEN.search(statement):
        raise ValidationError("The statement contains a data- or schema-modifying keyword.")


def _bind_values(bindings: dict[str, dict[str, Any]] | None) -> list:
    if not bindings:
        return []
    return [bindings[k]["value"] for k in sorted(bindings, key=lambda x: int(x))]


def _render(value: Any) -> str | None:
    """Snowflake returns every value as a string in the SQL API result set."""
    if value is None:
        return None
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, (list, tuple)):
        return "[" + ",".join("null" if v is None else str(v) for v in value) + "]"
    return str(value)


def _snowflake_type(sample: Any, declared: str) -> str:
    """Map a result column to a Snowflake SQL API rowType.

    Derived from the value and not from DuckDB's ``description``, because
    DuckDB reports every numeric column as ``NUMBER`` - integers, decimals and
    doubles alike - which would collapse the FIXED/REAL distinction that the
    client uses to decide whether to parse an integer or a float.
    """
    if isinstance(sample, bool):
        return "BOOLEAN"
    if isinstance(sample, int):
        return "FIXED"
    if isinstance(sample, Decimal):
        return "FIXED" if sample == sample.to_integral_value() else "REAL"
    if isinstance(sample, float):
        return "REAL"
    if isinstance(sample, datetime):
        return "TIMESTAMP_NTZ"
    if isinstance(sample, date):
        return "DATE"
    if isinstance(sample, (list, tuple)):
        return "ARRAY"
    if sample is None:
        t = str(declared).upper()
        return {"NUMBER": "REAL", "BOOL": "BOOLEAN", "DATE": "DATE",
                "DATETIME": "TIMESTAMP_NTZ"}.get(t, "TEXT")
    return "TEXT"


def _column_types(columns: list[tuple[str, str]], rows: list[tuple]) -> list[str]:
    """One pass over the result to find the first non-null value per column."""
    types: list[str] = []
    for idx, (_name, declared) in enumerate(columns):
        sample = None
        for row in rows:
            if row[idx] is not None:
                sample = row[idx]
                break
        types.append(_snowflake_type(sample, declared))
    return types


def _execute(statement: str, params: list, correlation_id: str) -> dict:
    from local_warehouse.warehouse import shared
    con = shared()
    try:
        with _LOCK:
            cur = con.execute(statement, params)
            columns = [(d[0], d[1]) for d in cur.description or []]
            rows = cur.fetchall()
    except Exception as exc:                                   # noqa: BLE001
        raise DataPlatformError(f"Query execution failed: {exc}") from exc
    types = _column_types(columns, rows)
    return {
        "resultSetMetaData": {
            "numRows": len(rows),
            "format": "jsonv2",
            "rowType": [{"name": name, "type": kind, "nullable": True}
                        for (name, _declared), kind in zip(columns, types, strict=True)],
        },
        "data": [[_render(v) for v in row] for row in rows],
        "code": "090001",
        "statementStatusUrl": None,
        "message": "Statement executed successfully.",
        "statementHandle": uuid.uuid4().hex,
        "createdOn": int(datetime.now().timestamp() * 1000),
        "correlationId": correlation_id,
    }


@app.get("/health", tags=["operations"])
async def health() -> dict:
    from local_warehouse.warehouse import shared
    try:
        shared().execute("SELECT 1").fetchone()
        return {"status": "UP", "service": "snowflake-data-api", "mode": _settings.platform_mode}
    except Exception as exc:                                   # noqa: BLE001
        raise DataPlatformError(f"Warehouse unavailable: {exc}") from exc


@app.post("/api/v2/statements", tags=["sql"])
async def submit(req: StatementRequest, request: Request,
                 claims: dict = Depends(require_scopes("customer:read"))) -> dict:
    _validate(req.statement)
    correlation_id = current_correlation_id()
    if req.asyncExec:
        handle = uuid.uuid4().hex
        _ASYNC_RESULTS[handle] = {"status": "RUNNING", "correlationId": correlation_id}
        try:
            _ASYNC_RESULTS[handle] = {
                "status": "SUCCEEDED",
                "result": _execute(req.statement, _bind_values(req.bindings), correlation_id)}
        except PlatformError as exc:
            _ASYNC_RESULTS[handle] = {"status": "FAILED", "message": exc.message}
        return {"statementHandle": handle, "code": "333334",
                "message": "Asynchronous execution in progress.",
                "statementStatusUrl": f"/api/v2/statements/{handle}"}
    return _execute(req.statement, _bind_values(req.bindings), correlation_id)


@app.get("/api/v2/statements/{handle}", tags=["sql"])
async def poll(handle: str, claims: dict = Depends(require_scopes("customer:read"))) -> dict:
    entry = _ASYNC_RESULTS.get(handle)
    if entry is None:
        raise ValidationError(f"Unknown statement handle '{handle}'.")
    if entry["status"] == "RUNNING":
        return {"statementHandle": handle, "code": "333334", "message": "Still running."}
    if entry["status"] == "FAILED":
        raise DataPlatformError(entry.get("message", "Statement failed."))
    return entry["result"]


class WriteRequest(BaseModel):
    rows: list[list[Any]] = Field(min_length=1, max_length=500)


@app.post("/internal/v1/writes/{operation}", tags=["internal"])
async def internal_write(operation: str, req: WriteRequest,
                         claims: dict = Depends(require_scopes("ai:write"))) -> dict:
    """Named, parameterised write operations - not arbitrary SQL.

    Present for two reasons.  The local one is mechanical: DuckDB allows exactly
    one read-write process, so the warehouse has a single owner and everything
    else reaches it over HTTP.  The architectural one survives the move to
    Snowflake: the AI service must be able to persist an insight and an audit
    row, and nothing else.  Giving it a general SQL channel would make a
    prompt-injection bug in the AI service into a data-exfiltration path.

    The allow-list lives in ``common/data_platform.py`` so that adding an
    operation is a reviewable change to one file.
    """
    from common.data_platform import WRITE_OPERATIONS
    statement = WRITE_OPERATIONS.get(operation)
    if statement is None:
        raise ValidationError(f"'{operation}' is not an approved write operation.",
                              details=[{"allowed": sorted(WRITE_OPERATIONS)}])
    from local_warehouse.warehouse import shared
    try:
        with _LOCK:
            shared().executemany(statement, [list(r) for r in req.rows])
    except Exception as exc:                                   # noqa: BLE001
        raise DataPlatformError(f"Write failed: {exc}") from exc
    return {"operation": operation, "rowsWritten": len(req.rows),
            "correlationId": current_correlation_id()}


@app.post("/api/v2/statements/{handle}/cancel", tags=["sql"])
async def cancel(handle: str, claims: dict = Depends(require_scopes("customer:read"))) -> dict:
    _ASYNC_RESULTS.pop(handle, None)
    return {"statementHandle": handle, "message": "Cancelled."}
