"""AI service.

Deliberately *not* a MuleSoft flow.  Generative work has a different latency
profile, a different cost model, a different failure mode and a different
governance regime from integration work, so it lives behind its own service and
is called by the Process API like any other dependency.  ADR-004 argues this in
full; the practical payoff is that the AI provider can be swapped, rate-limited,
or turned off entirely without touching a Mule application.
"""
from __future__ import annotations

from fastapi import Depends, FastAPI, Query
from pydantic import BaseModel, Field

from common.config import get_settings
from common.errors import (
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

from . import capabilities, prompts

_settings = get_settings()
configure_logging("ai-service", _settings.log_level, _settings.log_format)

app = FastAPI(
    title="Acme Customer Intelligence AI Service",
    version="1.3.0",
    description="Grounded generation over the Customer 360 AI context view.",
)
app.add_middleware(SecurityHeadersMiddleware)
# Generative calls are expensive; the AI service is limited far more tightly
# than the read APIs in front of it.
app.add_middleware(RateLimitMiddleware, requests=30, window=60)
app.add_middleware(CorrelationIdMiddleware)
app.add_exception_handler(PlatformError, platform_error_handler)
app.add_exception_handler(Exception, unhandled_error_handler)


class AnalysisRequest(BaseModel):
    capability: str = Field(default="SUMMARY",
                            description="SUMMARY | CHURN_EXPLANATION | NEXT_BEST_ACTION | "
                                        "SENTIMENT | GROUNDED_QA")
    question: str | None = Field(default=None, max_length=500,
                                 description="Required for GROUNDED_QA.")
    forceRefresh: bool = False


@app.get("/health", tags=["operations"])
async def health() -> dict:
    return {"status": "UP", "service": "ai-service", "provider": _settings.ai_provider,
            "model": _settings.ai_model, "promptLibrary": prompts.PROMPT_LIBRARY_VERSION}


@app.get("/api/v1/capabilities", tags=["operations"])
async def list_capabilities() -> dict:
    return {"capabilities": [
        {"capability": t.capability, "promptTemplateId": t.template_id,
         "promptVersion": t.version, "temperature": t.temperature,
         "maxOutputTokens": t.max_output_tokens}
        for t in prompts.REGISTRY.values()],
        "approvedActions": prompts.APPROVED_ACTIONS,
        "promptLibraryVersion": prompts.PROMPT_LIBRARY_VERSION}


@app.get("/api/v1/customers/{customer_id}/grounding", tags=["ai"])
async def grounding(customer_id: str,
                    claims: dict = Depends(require_scopes("ai:invoke"))) -> dict:
    """Exactly what the model would be shown.

    Exposing this is a governance feature, not a debugging convenience: when
    someone challenges a generated statement, the first question is always "what
    was the model actually told?", and the answer has to be inspectable without
    re-running the generation.
    """
    facts = await capabilities.load_grounding(customer_id)
    facts.pop("_injectionDetected", None)
    return {"customerId": customer_id, "facts": facts,
            "renderedFactsBlock": prompts.render_facts(facts),
            "correlationId": current_correlation_id()}


@app.post("/api/v1/customers/{customer_id}/analysis", tags=["ai"])
async def analyse(customer_id: str, request: AnalysisRequest,
                  claims: dict = Depends(require_scopes("ai:invoke"))) -> dict:
    capability = request.capability.upper()
    if capability not in prompts.REGISTRY:
        raise ValidationError(
            f"Unknown capability '{request.capability}'.",
            details=[{"field": "capability", "allowed": sorted(prompts.REGISTRY)}])
    if capability == "GROUNDED_QA" and not request.question:
        raise ValidationError("GROUNDED_QA requires a question.",
                              details=[{"field": "question", "issue": "required"}])
    return await capabilities.generate(
        capability, customer_id, question=request.question,
        client_id=claims.get("client_id", "unknown"), subject=claims.get("sub", "unknown"),
        force_refresh=request.forceRefresh)


@app.get("/api/v1/customers/{customer_id}/insights", tags=["ai"])
async def insights(customer_id: str,
                   types: str = Query(default="SUMMARY,CHURN_EXPLANATION,NEXT_BEST_ACTION"),
                   claims: dict = Depends(require_scopes("ai:invoke"))) -> dict:
    wanted = [t.strip().upper() for t in types.split(",") if t.strip()]
    produced, failures = [], []
    for capability in wanted:
        if capability not in prompts.REGISTRY:
            failures.append({"capability": capability, "reason": "unknown capability"})
            continue
        try:
            produced.append(await capabilities.generate(
                capability, customer_id,
                client_id=claims.get("client_id", "unknown"),
                subject=claims.get("sub", "unknown")))
        except PlatformError as exc:
            # One failing capability must not fail the whole response: partial
            # AI output is far more useful to an agent than an error page.
            failures.append({"capability": capability, "reason": exc.message})
    return {"customerId": customer_id, "insights": produced, "failures": failures,
            "correlationId": current_correlation_id()}


@app.get("/api/v1/audit/recent", tags=["operations"])
async def recent_audit(limit: int = Query(default=20, ge=1, le=200),
                       claims: dict = Depends(require_scopes("ai:invoke"))) -> dict:
    from local_warehouse.warehouse import shared
    rows = shared().execute(
        "SELECT REQUEST_ID, CORRELATION_ID, CAPABILITY, MODEL_PROVIDER, MODEL_NAME,"
        " INPUT_TOKENS, OUTPUT_TOKENS, ESTIMATED_COST_USD, LATENCY_MS, OUTCOME, REQUESTED_AT"
        " FROM ACME_EDP.AI.AI_REQUEST_AUDIT ORDER BY REQUESTED_AT DESC LIMIT ?",
        [limit]).fetchall()
    cols = ["requestId", "correlationId", "capability", "provider", "model", "inputTokens",
            "outputTokens", "estimatedCostUsd", "latencyMs", "outcome", "requestedAt"]
    return {"entries": [dict(zip(cols, [str(v) if hasattr(v, "isoformat") else v for v in r], strict=True))
                        for r in rows]}
