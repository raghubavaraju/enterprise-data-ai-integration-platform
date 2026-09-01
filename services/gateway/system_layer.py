"""System API layer.

Mirrors:
    mule/system-api/snowflake-data-api/   (Snowflake Data System API)
    mule/system-api/crm-system-api/       (CRM System API)

One system API per source system.  The contract of this layer is:

    * it speaks the *canonical* Acme vocabulary, never the source's;
    * it owns the source's connection details, credentials and quirks;
    * it contains no business logic and no cross-system joins - the moment a
      system API joins two sources it has become a process API with the wrong
      name and the wrong blast radius;
    * it is reusable: the CRM System API is the only place in the estate that
      knows how the CRM talks, so onboarding a second consumer costs nothing.

The normalisation done here is the reason the layer earns its keep.  The CRM
calls the key ``CustomerNumber``; the OMS calls order state ``status``; the
loyalty platform 404s for a customer who simply never enrolled.  Every consumer
would otherwise re-learn all three.
"""
from __future__ import annotations

import logging

from fastapi import Depends, FastAPI, Query

from common.config import get_settings
from common.errors import (
    NotFoundError,
    PlatformError,
    platform_error_handler,
    unhandled_error_handler,
)
from common.http_client import DownstreamClient, breaker_snapshots
from common.logging_config import configure_logging
from common.middleware import (
    CorrelationIdMiddleware,
    RateLimitMiddleware,
    SecurityHeadersMiddleware,
    current_correlation_id,
)
from common.security import require_scopes

from . import queries

log = logging.getLogger("system-api")
_settings = get_settings()
configure_logging("system-api", _settings.log_level, _settings.log_format)

app = FastAPI(title="Acme System API layer", version="1.0.0",
              description="Snowflake Data System API + source system APIs.")
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(RateLimitMiddleware)
app.add_middleware(CorrelationIdMiddleware)
app.add_exception_handler(PlatformError, platform_error_handler)
app.add_exception_handler(Exception, unhandled_error_handler)

snowflake = DownstreamClient("snowflake-sql-api", _settings.snowflake_data_api_url)
crm = DownstreamClient("crm", _settings.crm_system_url)
oms = DownstreamClient("oms", _settings.order_system_url)
support = DownstreamClient("support", _settings.support_system_url)
loyalty = DownstreamClient("loyalty", _settings.loyalty_system_url)


# ---------------------------------------------------------------------------
# Snowflake Data System API
# ---------------------------------------------------------------------------
def _bindings(*values) -> dict:
    """Snowflake SQL API bind format.  Never string interpolation."""
    types = {str: "TEXT", int: "FIXED", float: "REAL", bool: "BOOLEAN"}
    return {str(i + 1): {"type": types.get(type(v), "TEXT"), "value": v}
            for i, v in enumerate(values)}


def _rows(response: dict) -> list[dict]:
    """Snowflake returns arrays of strings plus rowType metadata; make dicts."""
    meta = response.get("resultSetMetaData", {}).get("rowType", [])
    names = [c["name"] for c in meta]
    types = {c["name"]: c["type"] for c in meta}
    out = []
    for row in response.get("data", []):
        record = {}
        for name, raw in zip(names, row, strict=True):
            record[name] = _coerce(raw, types.get(name, "TEXT"))
        out.append(record)
    return out


def _coerce(raw, snow_type: str):
    if raw is None:
        return None
    if snow_type == "FIXED":
        try:
            return int(float(raw))
        except (TypeError, ValueError):
            return raw
    if snow_type == "REAL":
        try:
            return float(raw)
        except (TypeError, ValueError):
            return raw
    if snow_type == "BOOLEAN":
        return str(raw).lower() in ("true", "1", "t")
    return raw


async def _query(statement: str, *params, timeout: int = 30) -> list[dict]:
    payload = {"statement": statement, "bindings": _bindings(*params), "timeout": timeout,
               "database": _settings.snowflake_database,
               "warehouse": _settings.snowflake_warehouse,
               "role": _settings.snowflake_role}
    body = await snowflake.post("/api/v2/statements", json=payload,
                                headers={"Authorization": _service_token(),
                                         # QUERY_TAG is how a Snowflake query is
                                         # tied back to the API call that caused
                                         # it - see docs/observability.md.
                                         "x-query-tag": current_correlation_id()})
    return _rows(body)


def _service_token() -> str:
    """Platform-to-platform credential.

    In cloud mode this is a key-pair JWT for the SVC_MULE_INTEGRATION Snowflake
    user, minted per call and never stored.  Locally it is a client-credentials
    token from the mock authorisation server.  Either way it is *not* the
    caller's token: the caller's entitlements are enforced at the experience
    layer, and the data platform sees only the platform identity.
    """
    from common.security import issue_token
    return "Bearer " + issue_token("acme-batch-client", _settings.oauth_client_secret,
                                   "customer:read insights:read")["access_token"]


@app.get("/health", tags=["operations"])
async def health() -> dict:
    return {"status": "UP", "service": "system-api", "circuitBreakers": breaker_snapshots()}


@app.get("/api/v1/snowflake/customers/{customer_id}/360", tags=["snowflake"])
async def sf_customer_360(customer_id: str,
                          _: dict = Depends(require_scopes("customer:read"))) -> dict:
    rows = await _query(queries.CUSTOMER_360, customer_id)
    if not rows:
        raise NotFoundError(f"No Customer 360 record for '{customer_id}'.")
    return rows[0]


def _camel(name: str) -> str:
    """SCREAMING_SNAKE column -> camelCase field.

    The warehouse's naming convention stops at this layer.  Letting database
    column names travel to a client makes every future column rename a breaking
    API change - which is exactly the coupling the system API layer exists to
    prevent.
    """
    head, *rest = name.lower().split("_")
    return head + "".join(part.title() for part in rest)


def _canonical(rows: list[dict]) -> list[dict]:
    return [{_camel(k): v for k, v in row.items()} for row in rows]


@app.get("/api/v1/snowflake/customers/{customer_id}/orders", tags=["snowflake"])
async def sf_customer_orders(customer_id: str, limit: int = Query(20, ge=1, le=200),
                             offset: int = Query(0, ge=0),
                             _: dict = Depends(require_scopes("customer:read"))) -> dict:
    rows = await _query(queries.CUSTOMER_ORDERS, customer_id, limit, offset)
    total = int((await _query(queries.CUSTOMER_ORDER_COUNT, customer_id))[0]["TOTAL"] or 0)
    return {"data": _canonical(rows),
            "pagination": {"limit": limit, "offset": offset, "total": total,
                           "hasMore": offset + limit < total}}


@app.get("/api/v1/snowflake/customers/{customer_id}/cases", tags=["snowflake"])
async def sf_customer_cases(customer_id: str, limit: int = Query(20, ge=1, le=200),
                            _: dict = Depends(require_scopes("customer:read"))) -> dict:
    return {"data": _canonical(await _query(queries.CUSTOMER_CASES, customer_id, limit))}


@app.get("/api/v1/snowflake/customers/{customer_id}/churn-risk", tags=["snowflake"])
async def sf_churn(customer_id: str,
                   _: dict = Depends(require_scopes("insights:read"))) -> dict:
    rows = await _query(queries.CHURN_RISK, customer_id)
    if not rows:
        raise NotFoundError(f"No churn score for '{customer_id}'.")
    return rows[0]


@app.get("/api/v1/snowflake/cohorts/high-risk", tags=["snowflake"])
async def sf_high_risk(limit: int = Query(25, ge=1, le=200),
                       _: dict = Depends(require_scopes("insights:read"))) -> dict:
    return {"data": _canonical(await _query(queries.HIGH_RISK_COHORT, limit))}


@app.get("/api/v1/snowflake/governance/data-quality", tags=["snowflake"])
async def sf_dq(_: dict = Depends(require_scopes("insights:read"))) -> dict:
    return {"data": _canonical(await _query(queries.DQ_SCORECARD))}


@app.get("/api/v1/snowflake/platform/freshness", tags=["snowflake"])
async def sf_freshness(_: dict = Depends(require_scopes("customer:read"))) -> dict:
    return (await _query(queries.PLATFORM_FRESHNESS))[0]


# ---------------------------------------------------------------------------
# Source system APIs - canonical vocabulary, source quirks absorbed here
# ---------------------------------------------------------------------------
@app.get("/api/v1/crm/customers/{customer_id}", tags=["crm"])
async def crm_customer(customer_id: str, fault: str | None = None,
                       _: dict = Depends(require_scopes("customer:read"))) -> dict:
    params = {"__fault": fault} if fault else None
    raw = await crm.get(f"/api/v1/customers/{customer_id}", params=params)
    # Canonical shape.  The CRM's "CustomerNumber" vocabulary stops here.
    return {
        "customerId": raw.get("customerId"),
        "firstName": raw.get("firstName"),
        "lastName": raw.get("lastName"),
        "email": raw.get("email"),
        "phone": raw.get("phone"),
        "birthDate": raw.get("birthDate"),
        "segment": raw.get("customerSegment"),
        "preferredChannel": raw.get("preferredChannel"),
        "marketingOptIn": raw.get("marketingOptIn"),
        "status": raw.get("status"),
        "createdAt": raw.get("createdAt"),
        "sourceSystem": "CRM",
    }


@app.get("/api/v1/orders", tags=["oms"])
async def oms_orders(customerId: str, limit: int = Query(20, ge=1, le=200),
                     fault: str | None = None,
                     _: dict = Depends(require_scopes("customer:read"))) -> dict:
    params = {"customerId": customerId, "limit": limit}
    if fault:
        params["__fault"] = fault
    raw = await oms.get("/api/v1/orders", params=params)
    return {"data": [{
        "orderId": o["orderId"], "orderDate": o["orderDate"],
        "status": o["orderStatus"],             # OMS "orderStatus" -> canonical "status"
        "channel": o["channel"], "currency": o["currency"],
        "grossAmount": o["orderAmount"], "discountAmount": o.get("discountAmount", 0),
        "shippingAmount": o.get("shippingAmount", 0),
        "netAmount": round(o["orderAmount"] - o.get("discountAmount", 0), 2),
    } for o in raw.get("data", [])],
        "pagination": raw.get("pagination", {})}


@app.get("/api/v1/support/cases", tags=["support"])
async def support_cases(customerId: str, limit: int = Query(20, ge=1, le=200),
                        fault: str | None = None,
                        _: dict = Depends(require_scopes("customer:read"))) -> dict:
    params = {"customerId": customerId, "limit": limit}
    if fault:
        params["__fault"] = fault
    raw = await support.get("/api/v1/cases", params=params)
    return {"data": raw.get("data", []), "pagination": raw.get("pagination", {})}


@app.get("/api/v1/loyalty/accounts/{customer_id}", tags=["loyalty"])
async def loyalty_account(customer_id: str, fault: str | None = None,
                          _: dict = Depends(require_scopes("customer:read"))) -> dict:
    """A customer who never enrolled is not an error.

    The loyalty platform answers 404 for "not enrolled" and for "no such
    customer" alike.  Translating that into a canonical, unambiguous
    ``enrolled: false`` is exactly the kind of source quirk that belongs in a
    system API and nowhere else.
    """
    params = {"__fault": fault} if fault else None
    try:
        raw = await loyalty.get(f"/api/v1/loyalty-accounts/by-customer/{customer_id}",
                                params=params)
    except NotFoundError:
        return {"customerId": customer_id, "enrolled": False, "tier": None,
                "pointsBalance": 0, "status": "NOT_ENROLLED"}
    return {"customerId": customer_id, "enrolled": True,
            "loyaltyAccountId": raw["loyaltyAccountId"], "tier": raw["tier"],
            "pointsBalance": raw["pointsBalance"], "status": raw["status"],
            "enrolledAt": raw["enrolledAt"], "lastActivityAt": raw["lastActivityAt"]}
