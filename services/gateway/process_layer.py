"""Process API layer.

Mirrors:
    mule/process-api/customer-360-process-api.xml
    mule/process-api/customer-intelligence-process-api.xml

This is where the business process lives: orchestration across systems,
enrichment, business rules, and - most importantly - the *degradation policy*.

The degradation policy is the part that separates a demo from a platform.  A
Customer 360 assembled from five systems will, on any given day, have one of
them unavailable.  Three possible behaviours:

    (a) fail the whole request            - unacceptable; an agent with a
                                            customer on the phone gets nothing
    (b) silently return partial data      - worse; the agent cannot tell that
                                            "no orders" means "no orders"
    (c) return what is available, name    - what this layer does
        what is missing, and say why

Option (c) requires the response contract to carry ``degradedFields`` and
``partial``, which is why they are in the API specification and not being
an afterthought.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import Depends, FastAPI, Header, Query
from pydantic import BaseModel, Field

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
from common.resilience import Bulkhead, IdempotencyStore
from common.security import require_scopes

log = logging.getLogger("process-api")
_settings = get_settings()
configure_logging("process-api", _settings.log_level, _settings.log_format)

app = FastAPI(title="Acme Process API layer", version="1.0.0")
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(RateLimitMiddleware)
app.add_middleware(CorrelationIdMiddleware)
app.add_exception_handler(PlatformError, platform_error_handler)
app.add_exception_handler(Exception, unhandled_error_handler)

system = DownstreamClient("system-api", _settings.system_api_url)
ai = DownstreamClient("ai-service", _settings.ai_service_url)

# Bounded concurrency towards the AI service: generative calls are slow and
# expensive, and letting a traffic spike fan out to the provider is how a
# platform turns a busy morning into an invoice.
_ai_bulkhead = Bulkhead(limit=4)
_idempotency = IdempotencyStore()


def _auth() -> dict[str, str]:
    from common.security import issue_token
    token = issue_token("acme-portal-client", _settings.oauth_client_secret,
                        "customer:read insights:read ai:invoke")["access_token"]
    return {"Authorization": f"Bearer {token}"}


class Degradation:
    """Collects, per request, which parts of the response could not be built."""

    def __init__(self) -> None:
        self.fields: list[dict[str, str]] = []

    def record(self, field: str, dependency: str, exc: Exception) -> None:
        reason = getattr(exc, "message", None) or exc.__class__.__name__
        code = getattr(exc, "error_code", "PLATFORM:DOWNSTREAM_UNAVAILABLE")
        self.fields.append({"field": field, "dependency": dependency,
                            "errorCode": code, "reason": reason})
        log.warning("degraded_field", extra={"field": field, "dependency": dependency,
                                             "reason": reason})

    @property
    def partial(self) -> bool:
        return bool(self.fields)


async def _safe(coro, degradation: Degradation, field: str, dependency: str,
                default: Any = None):
    try:
        return await coro
    except NotFoundError:
        # Absence is a fact, not a failure: "this customer has no loyalty
        # account" is a legitimate answer and must not be reported as an outage.
        return default
    except Exception as exc:                                     # noqa: BLE001
        degradation.record(field, dependency, exc)
        return default


@app.get("/health", tags=["operations"])
async def health() -> dict:
    return {"status": "UP", "service": "process-api", "circuitBreakers": breaker_snapshots()}


@app.get("/api/v1/customers/{customer_id}/360", tags=["customer-360"])
async def customer_360(customer_id: str, includeOrders: bool = True,
                       includeSupport: bool = True, includeAi: bool = False,
                       orderLimit: int = Query(10, ge=1, le=100),
                       _: dict = Depends(require_scopes("customer:read"))) -> dict:
    """Assemble the Customer 360.

    The five reads are issued concurrently.  Sequential orchestration would make
    the response as slow as the sum of its dependencies instead of as slow as
    its slowest one, and this endpoint carries an 800 ms p95 target.
    """
    deg = Degradation()
    headers = _auth()

    core_task = system.get(f"/api/v1/snowflake/customers/{customer_id}/360", headers=headers)
    tasks: dict[str, Any] = {
        "churn": system.get(f"/api/v1/snowflake/customers/{customer_id}/churn-risk",
                            headers=headers),
    }
    if includeOrders:
        tasks["orders"] = system.get(f"/api/v1/snowflake/customers/{customer_id}/orders",
                                     params={"limit": orderLimit}, headers=headers)
    if includeSupport:
        tasks["cases"] = system.get(f"/api/v1/snowflake/customers/{customer_id}/cases",
                                    params={"limit": 10}, headers=headers)

    # The core profile is the only hard dependency: without it there is no
    # customer to describe, so a failure here is a real 404/503.
    core = await core_task

    results = await asyncio.gather(
        *[_safe(c, deg, name, "snowflake", default=None) for name, c in tasks.items()],
        return_exceptions=False)
    fetched = dict(zip(tasks.keys(), results, strict=True))

    ai_block = None
    if includeAi:
        async with _ai_bulkhead:
            ai_block = await _safe(
                ai.get(f"/api/v1/customers/{customer_id}/insights",
                       params={"types": "SUMMARY,CHURN_EXPLANATION"}, headers=headers),
                deg, "aiInsights", "ai-service")

    return {
        "customerId": customer_id,
        "profile": _profile(core),
        "orders": (fetched.get("orders") or {}).get("data", []) if includeOrders else [],
        "orderPagination": (fetched.get("orders") or {}).get("pagination"),
        "support": (fetched.get("cases") or {}).get("data", []) if includeSupport else [],
        "loyalty": _loyalty(core),
        "analytics": _analytics(core),
        "churnRisk": _churn(fetched.get("churn")),
        "aiInsights": ai_block,
        "dataQuality": {
            "completenessScore": core.get("DATA_COMPLETENESS_SCORE"),
            "contributingSources": (core.get("CONTRIBUTING_SOURCES") or "").split(","),
            "asOf": core.get("AS_OF_TIMESTAMP"),
        },
        "partial": deg.partial,
        "degradedFields": deg.fields,
        "correlationId": current_correlation_id(),
    }


def _profile(core: dict) -> dict:
    return {
        "fullName": core.get("FULL_NAME"), "email": core.get("EMAIL"),
        "phone": core.get("PHONE"), "birthDate": core.get("BIRTH_DATE"),
        "segment": core.get("CUSTOMER_SEGMENT"), "status": core.get("CUSTOMER_STATUS"),
        "preferredChannel": core.get("PREFERRED_CHANNEL"),
        "marketingOptIn": core.get("MARKETING_OPT_IN"),
        "customerSince": core.get("CUSTOMER_SINCE"), "tenureDays": core.get("TENURE_DAYS"),
        "location": {"city": core.get("PRIMARY_CITY"), "state": core.get("PRIMARY_STATE"),
                     "country": core.get("PRIMARY_COUNTRY")},
    }


def _loyalty(core: dict) -> dict:
    return {"tier": core.get("LOYALTY_TIER"), "status": core.get("LOYALTY_STATUS"),
            "pointsBalance": core.get("LOYALTY_POINTS_BALANCE"),
            "enrolledAt": core.get("LOYALTY_ENROLLED_AT")}


def _analytics(core: dict) -> dict:
    return {
        "totalOrders": core.get("TOTAL_ORDERS"),
        "totalNetRevenue": core.get("TOTAL_NET_REVENUE"),
        "avgOrderValue": core.get("AVG_ORDER_VALUE"),
        "orderFrequencyPerYear": core.get("ORDER_FREQUENCY_PER_YEAR"),
        "lastOrderDate": core.get("LAST_ORDER_DATE"),
        "daysSinceLastOrder": core.get("DAYS_SINCE_LAST_ORDER"),
        "revenueLast365d": core.get("REVENUE_LAST_365D"),
        "returnRate": core.get("RETURN_RATE"),
        "totalCases": core.get("TOTAL_CASES"), "openCases": core.get("OPEN_CASES"),
        "avgCsat": core.get("AVG_CSAT"), "topCaseType": core.get("TOP_CASE_TYPE"),
        "engagementScore": core.get("ENGAGEMENT_SCORE"),
        "customerLifetimeValue": core.get("CUSTOMER_LIFETIME_VALUE"),
        "predictedClv12m": core.get("PREDICTED_CLV_12M"),
        "valueTier": core.get("VALUE_TIER"),
    }


def _churn(row: dict | None) -> dict | None:
    if not row:
        return None
    drivers = []
    for i in (1, 2, 3):
        name = row.get(f"TOP_DRIVER_{i}")
        if name:
            drivers.append({"rank": i, "driver": name,
                            "contribution": row.get(f"TOP_DRIVER_{i}_CONTRIB")})
    return {"churnProbability": row.get("CHURN_PROBABILITY"),
            "riskBand": row.get("CHURN_RISK_BAND"),
            "model": {"name": row.get("MODEL_NAME"), "version": row.get("MODEL_VERSION"),
                      "method": row.get("SCORING_METHOD"),
                      "featureSetVersion": row.get("FEATURE_SET_VERSION")},
            "drivers": drivers, "scoreDate": row.get("SCORE_DATE")}


# ---------------------------------------------------------------------------
# Customer Intelligence process
# ---------------------------------------------------------------------------
class AnalysisRequest(BaseModel):
    capability: str = Field(default="SUMMARY")
    question: str | None = None
    forceRefresh: bool = False


@app.post("/api/v1/customers/{customer_id}/ai-analysis", tags=["intelligence"])
async def ai_analysis(customer_id: str, request: AnalysisRequest,
                      idempotency_key: str | None = Header(default=None,
                                                           alias="Idempotency-Key"),
                      _: dict = Depends(require_scopes("ai:invoke"))) -> dict:
    """Trigger a generative analysis.

    Idempotency is enforced here rather than at the experience layer because
    this is the boundary where a repeated call costs real money.  A client that
    retries on a timeout - which every well-behaved client does - would
    otherwise be billed twice for the same answer.
    """
    if idempotency_key:
        cached = _idempotency.get(idempotency_key)
        if cached is not None:
            return {**cached, "idempotentReplay": True}

    async with _ai_bulkhead:
        result = await ai.post(
            f"/api/v1/customers/{customer_id}/analysis",
            json={"capability": request.capability, "question": request.question,
                  "forceRefresh": request.forceRefresh},
            headers=_auth(),
            # Never retry a generative call automatically: it is not idempotent
            # from a cost perspective, and a slow response is usually a slow
            # model rather than a lost request.
            retries=1)

    if idempotency_key:
        _idempotency.put(idempotency_key, result)
    return result


@app.get("/api/v1/customers/{customer_id}/insights", tags=["intelligence"])
async def insights(customer_id: str, types: str = "SUMMARY,CHURN_EXPLANATION,NEXT_BEST_ACTION",
                   _: dict = Depends(require_scopes("insights:read"))) -> dict:
    deg = Degradation()
    headers = _auth()
    churn = await _safe(system.get(f"/api/v1/snowflake/customers/{customer_id}/churn-risk",
                                   headers=headers), deg, "churnRisk", "snowflake")
    async with _ai_bulkhead:
        generated = await _safe(
            ai.get(f"/api/v1/customers/{customer_id}/insights", params={"types": types},
                   headers=headers, retries=1), deg, "aiInsights", "ai-service")
    return {"customerId": customer_id, "churnRisk": _churn(churn),
            "aiInsights": generated, "partial": deg.partial, "degradedFields": deg.fields,
            "correlationId": current_correlation_id()}


@app.get("/api/v1/cohorts/high-risk", tags=["intelligence"])
async def high_risk(limit: int = Query(25, ge=1, le=200),
                    _: dict = Depends(require_scopes("insights:read"))) -> dict:
    return await system.get("/api/v1/snowflake/cohorts/high-risk",
                            params={"limit": limit}, headers=_auth())


@app.get("/api/v1/governance/data-quality", tags=["governance"])
async def data_quality(_: dict = Depends(require_scopes("insights:read"))) -> dict:
    return await system.get("/api/v1/snowflake/governance/data-quality", headers=_auth())
