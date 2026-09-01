"""Experience API layer.

Mirrors:
    mule/experience-api/customer-experience-api.xml
    mule/experience-api/ai-insights-api.xml

The experience layer exists to serve *one* consumer well.  Its job:

    * shape the payload for that consumer (a service-desk web app here);
    * apply entitlement-based masking - the same endpoint returns different
      field values to a client without the ``pii:read`` scope;
    * enforce the client-facing SLA (rate limit, timeout, cache);
    * expose a stable contract so that a change in a process or system API is
      invisible to the consumer.

It contains no orchestration and no data access.  If a second consumer needs a
different shape - a mobile app, a partner - it gets its own experience API over
the same process API rather than query parameters bolted onto this one.
"""
from __future__ import annotations

import logging
import time

from fastapi import Depends, FastAPI, Form, Header, Query, Request
from pydantic import BaseModel, Field

from common.config import get_settings
from common.errors import (
    PlatformError,
    ValidationError,
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
from common.pii import apply_profile_masking
from common.security import issue_token, require_scopes

log = logging.getLogger("experience-api")
_settings = get_settings()
configure_logging("experience-api", _settings.log_level, _settings.log_format)

app = FastAPI(
    title="Acme Customer Experience API",
    version="1.0.0",
    description="Client-facing API for the Acme service-desk application.",
)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(RateLimitMiddleware)
app.add_middleware(CorrelationIdMiddleware)
app.add_exception_handler(PlatformError, platform_error_handler)
app.add_exception_handler(Exception, unhandled_error_handler)

process = DownstreamClient("process-api", _settings.process_api_url)


def _auth() -> dict[str, str]:
    token = issue_token("acme-portal-client", _settings.oauth_client_secret,
                        "customer:read insights:read ai:invoke")["access_token"]
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Mock authorisation server (local mode only)
# ---------------------------------------------------------------------------
@app.post("/oauth/token", tags=["security"])
async def token(grant_type: str = Form(default="client_credentials"),
                client_id: str = Form(...), client_secret: str = Form(...),
                scope: str | None = Form(default=None)) -> dict:
    """OAuth 2.0 client-credentials endpoint.

    Present so the full token flow can be exercised offline.  In any real
    environment this endpoint does not exist in the application: tokens come
    from Anypoint Access Management or the enterprise IdP, and the API only ever
    *validates* them.  An application that issues its own tokens has made itself
    the identity provider, which is exactly the coupling API-led is meant to
    avoid.
    """
    if grant_type != "client_credentials":
        raise ValidationError("Only the client_credentials grant is supported.")
    return issue_token(client_id, client_secret, scope)


@app.get("/health", tags=["operations"])
async def health() -> dict:
    return {"status": "UP", "service": "experience-api",
            "circuitBreakers": breaker_snapshots()}


@app.get("/api/v1/customers/{customer_id}/360", tags=["customers"])
async def customer_360(customer_id: str, request: Request,
                       includeOrders: bool = True, includeSupport: bool = True,
                       includeAi: bool = False, orderLimit: int = Query(10, ge=1, le=100),
                       claims: dict = Depends(require_scopes("customer:read"))) -> dict:
    started = time.perf_counter()
    upstream = await process.get(
        f"/api/v1/customers/{customer_id}/360",
        params={"includeOrders": includeOrders, "includeSupport": includeSupport,
                "includeAi": includeAi, "orderLimit": orderLimit},
        headers=_auth())

    # Entitlement-based masking.  The same resource, two different truths,
    # decided by the token - not by a query parameter the client controls.
    may_see_pii = "pii:read" in claims.get("scope", "").split()
    upstream["profile"] = apply_profile_masking(upstream.get("profile", {}), may_see_pii)

    return {
        "customerId": upstream["customerId"],
        "profile": upstream["profile"],
        "orders": upstream.get("orders", []),
        "support": upstream.get("support", []),
        "loyalty": upstream.get("loyalty"),
        "analytics": upstream.get("analytics"),
        "aiInsights": _shape_ai(upstream.get("aiInsights")),
        "churnRisk": upstream.get("churnRisk"),
        "meta": {
            "partial": upstream.get("partial", False),
            "degradedFields": [d["field"] for d in upstream.get("degradedFields", [])],
            "dataCompletenessScore": upstream.get("dataQuality", {}).get("completenessScore"),
            "contributingSources": upstream.get("dataQuality", {}).get("contributingSources"),
            "asOf": upstream.get("dataQuality", {}).get("asOf"),
            "correlationId": current_correlation_id(),
            "elapsedMs": round((time.perf_counter() - started) * 1000, 1),
        },
    }


@app.get("/api/v1/customers/{customer_id}/insights", tags=["insights"])
async def insights(customer_id: str,
                   types: str = Query(default="SUMMARY,CHURN_EXPLANATION,NEXT_BEST_ACTION"),
                   claims: dict = Depends(require_scopes("insights:read"))) -> dict:
    upstream = await process.get(f"/api/v1/customers/{customer_id}/insights",
                                 params={"types": types}, headers=_auth())
    return {"customerId": customer_id, "churnRisk": upstream.get("churnRisk"),
            "insights": _shape_ai(upstream.get("aiInsights")),
            "meta": {"partial": upstream.get("partial", False),
                     "degradedFields": [d["field"] for d in upstream.get("degradedFields", [])],
                     "correlationId": current_correlation_id()}}


@app.get("/api/v1/customers/{customer_id}/churn-risk", tags=["insights"])
async def churn_risk(customer_id: str,
                     claims: dict = Depends(require_scopes("insights:read"))) -> dict:
    upstream = await process.get(f"/api/v1/customers/{customer_id}/360",
                                 params={"includeOrders": False, "includeSupport": False},
                                 headers=_auth())
    risk = upstream.get("churnRisk")
    if not risk:
        raise PlatformError("No churn score is available for this customer.")
    return {"customerId": customer_id, **risk,
            "meta": {"correlationId": current_correlation_id()}}


class AnalysisRequest(BaseModel):
    capability: str = Field(default="SUMMARY")
    question: str | None = Field(default=None, max_length=500)
    forceRefresh: bool = False


@app.post("/api/v1/customers/{customer_id}/ai-analysis", tags=["insights"])
async def ai_analysis(customer_id: str, body: AnalysisRequest,
                      idempotency_key: str | None = Header(default=None,
                                                           alias="Idempotency-Key"),
                      claims: dict = Depends(require_scopes("ai:invoke"))) -> dict:
    headers = _auth()
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key
    result = await process.post(f"/api/v1/customers/{customer_id}/ai-analysis",
                                json=body.model_dump(), headers=headers, retries=1)
    return {"customerId": customer_id, **_shape_insight(result),
            "meta": {"correlationId": current_correlation_id(),
                     "idempotentReplay": result.get("idempotentReplay", False)}}


@app.get("/api/v1/cohorts/high-risk", tags=["insights"])
async def high_risk(limit: int = Query(25, ge=1, le=200),
                    claims: dict = Depends(require_scopes("insights:read"))) -> dict:
    return await process.get("/api/v1/cohorts/high-risk", params={"limit": limit},
                             headers=_auth())


@app.get("/api/v1/governance/data-quality", tags=["governance"])
async def data_quality(claims: dict = Depends(require_scopes("insights:read"))) -> dict:
    return await process.get("/api/v1/governance/data-quality", headers=_auth())


def _shape_ai(block: dict | None) -> dict | None:
    if not block:
        return None
    return {"generated": [_shape_insight(i) for i in block.get("insights", [])],
            "unavailable": block.get("failures", [])}


def _shape_insight(insight: dict) -> dict:
    """Trim provenance to what a client application actually needs.

    The full provenance (grounding snapshot, token counts, prompt version) stays
    in AI.AI_CUSTOMER_INSIGHTS.  A client needs to know *whether* it can trust
    and display the text, and whether a human still has to approve it - not the
    prompt template id.
    """
    if not insight:
        return {}
    quality = insight.get("quality", {})
    review = insight.get("review", {})
    return {
        "type": insight.get("insightType"),
        "text": insight.get("generatedText"),
        "structured": insight.get("structured"),
        "confidence": quality.get("confidence"),
        "requiresHumanApproval": review.get("requiresHumanApproval", False),
        "reviewStatus": review.get("status"),
        "generatedBy": {"provider": insight.get("model", {}).get("provider"),
                        "model": insight.get("model", {}).get("name")},
        "sources": insight.get("grounding", {}).get("knowledgeArticles", []),
        "generatedAt": insight.get("generatedAt"),
        "cached": insight.get("cached", False),
        # Displayed verbatim by the service-desk UI next to any generated text.
        "disclaimer": "AI-generated from Acme's own customer data. Verify before "
                      "acting on it.",
    }
