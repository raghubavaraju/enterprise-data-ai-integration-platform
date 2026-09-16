"""Store Associate Experience API layer.

Mirrors:
    mule/experience-api/store-associate-experience-api.xml

This is the platform's second experience API, and it exists to answer a claim
made everywhere else in this repository but never, until this file, actually
demonstrated: that a new consumer is a new experience API over the *same*
process API, not a new integration.

    Customer Experience API (services/gateway/experience_layer.py)
        consumer: the service-desk web app
        shape:    the full Customer 360 - orders, support, loyalty, churn, AI
        identity: acme-portal-client / acme-servicedesk-client
        may see:  unmasked PII, for the client entitled to pii:read

    Store Associate Experience API (this file)
        consumer: a handheld device shared by staff on the retail floor
        shape:    the minimum needed to help a customer at the counter
        identity: acme-store-app-client - customer:read only, nothing else
        may see:  never unmasked PII - a screen more than one person can see
                  is not the place for a full name and an e-mail address

Both call ``process.get("/api/v1/customers/{id}/360", ...)``.  Neither the
process layer nor the system layer beneath it has a single line changed to
support this file - which is the point.  ``tests/api/test_gateway_layers.py::
TestStoreAssociateExperienceLayer::test_both_experience_apis_reuse_the_same_process_endpoint``
asserts this directly rather than leaving it as an architectural claim to take
on faith.

What is deliberately NOT here: orders history beyond a short recent list,
support cases, churn risk, AI insight.  A store associate is not the audience
for a retention conversation; that stays behind ``insights:read`` and
``ai:invoke``, which this client is never issued.
"""
from __future__ import annotations

import logging
import time

from fastapi import Depends, FastAPI, Form, Query, Request

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

log = logging.getLogger("store-associate-api")
_settings = get_settings()
configure_logging("store-associate-api", _settings.log_level, _settings.log_format)

app = FastAPI(
    title="Acme Store Associate API",
    version="1.0.0",
    description="Client-facing API for the handheld device used by store-floor staff.",
)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(RateLimitMiddleware)
app.add_middleware(CorrelationIdMiddleware)
app.add_exception_handler(PlatformError, platform_error_handler)
app.add_exception_handler(Exception, unhandled_error_handler)

# Same process API, same DownstreamClient wrapper, same circuit breaker and
# retry policy as the service-desk experience API. Nothing downstream knows or
# cares that a second consumer exists.
process = DownstreamClient("process-api", _settings.process_api_url)

# Least privilege applies to platform-to-platform calls too. The service-desk
# layer's own service identity holds insights:read and ai:invoke because it
# calls endpoints that need them; this one never does, so its own token asks
# for customer:read alone.
_SERVICE_CLIENT_ID = "acme-store-app-client"


def _auth() -> dict[str, str]:
    token = issue_token(_SERVICE_CLIENT_ID, _settings.oauth_client_secret,
                        "customer:read")["access_token"]
    return {"Authorization": f"Bearer {token}"}


@app.post("/oauth/token", tags=["security"])
async def token(grant_type: str = Form(default="client_credentials"),
                client_id: str = Form(...), client_secret: str = Form(...),
                scope: str | None = Form(default=None)) -> dict:
    """Local-mode-only token issuance. See experience_layer.token for why a
    real deployment never has this endpoint at all."""
    if grant_type != "client_credentials":
        raise ValidationError("Only the client_credentials grant is supported.")
    return issue_token(client_id, client_secret, scope)


@app.get("/health", tags=["operations"])
async def health() -> dict:
    return {"status": "UP", "service": "store-associate-api",
            "circuitBreakers": breaker_snapshots()}


@app.get("/api/v1/associate/customers/{customer_id}/lookup", tags=["associate"])
async def lookup(customer_id: str, request: Request,
                 claims: dict = Depends(require_scopes("customer:read"))) -> dict:
    """Enough to greet a customer by name and know how to treat them.

    One deliberate choice distinguishes this from ``/customers/{id}/360``
    beyond masking: e-mail, phone and date of birth are not merely masked,
    they are absent from the shape entirely. A field that is not in the
    contract cannot be screenshotted, and there is no store-floor workflow
    that needs a customer's e-mail address on screen.

    The single downstream call asks for none of the optional blocks - no
    orders, no support history, no AI - because a lookup at the counter has no
    latency budget to spend on data this screen will not show.
    """
    started = time.perf_counter()
    upstream = await process.get(
        f"/api/v1/customers/{customer_id}/360",
        params={"includeOrders": False, "includeSupport": False, "includeAi": False},
        headers=_auth())

    # This client is never issued pii:read (see common/security.py), so this
    # is always False in practice. It is still read from the token rather than
    # hard-coded, because a masking rule that only works by construction is
    # one bad client registration away from a data exposure.
    may_see_pii = "pii:read" in claims.get("scope", "").split()
    masked_name = apply_profile_masking(
        {"fullName": (upstream.get("profile") or {}).get("fullName")}, may_see_pii)

    analytics = upstream.get("analytics") or {}
    profile = upstream.get("profile") or {}

    return {
        "customerId": upstream["customerId"],
        "displayName": masked_name.get("fullName"),
        "segment": profile.get("segment"),
        "status": profile.get("status"),
        # A derived flag, not the raw value tier: the associate app needs a
        # yes/no signal for "give this customer extra attention", not the
        # customer-lifetime-value figure that produced it.
        "vip": profile.get("segment") == "PREMIUM" or analytics.get("valueTier") == "HIGH",
        "loyalty": upstream.get("loyalty"),
        "meta": {
            "masked": bool(masked_name.get("_masked", False)),
            "partial": upstream.get("partial", False),
            "degradedFields": [d["field"] for d in upstream.get("degradedFields", [])],
            "dataCompletenessScore": upstream.get("dataQuality", {}).get("completenessScore"),
            "asOf": upstream.get("dataQuality", {}).get("asOf"),
            "correlationId": current_correlation_id(),
            "elapsedMs": round((time.perf_counter() - started) * 1000, 1),
        },
    }


@app.get("/api/v1/associate/customers/{customer_id}/recent-orders", tags=["associate"])
async def recent_orders(customer_id: str,
                        limit: int = Query(5, ge=1, le=20),
                        claims: dict = Depends(require_scopes("customer:read"))) -> dict:
    """A short order list for a return, exchange or "where is my order" query.

    Reshaped, not just passed through: the process layer's ``orderStatus`` and
    ``totalUnits`` become this consumer's ``status`` and ``itemCount``. Two
    experience APIs are free to name the same underlying fact differently for
    their own audience, which is exactly why reshaping happens at this edge
    and not in the process layer that both of them share.
    """
    upstream = await process.get(
        f"/api/v1/customers/{customer_id}/360",
        params={"includeOrders": True, "includeSupport": False, "includeAi": False,
               "orderLimit": limit},
        headers=_auth())

    orders = [{
        "orderId": o.get("orderId"),
        "orderDate": o.get("orderDate"),
        "status": o.get("orderStatus"),
        "netAmount": o.get("netAmount"),
        "itemCount": o.get("totalUnits"),
    } for o in upstream.get("orders", [])]

    return {
        "customerId": customer_id,
        "orders": orders,
        "meta": {
            "partial": upstream.get("partial", False),
            "degradedFields": [d["field"] for d in upstream.get("degradedFields", [])],
            "correlationId": current_correlation_id(),
        },
    }
