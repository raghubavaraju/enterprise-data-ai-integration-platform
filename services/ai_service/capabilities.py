"""The five AI capabilities, and the pipeline every one of them goes through.

    1. fetch grounding data from the AI-safe view (never from a source system)
    2. redact and injection-check anything free-text
    3. render a versioned prompt with an explicit FACTS block
    4. call the provider
    5. validate the output against the grounding data
    6. evaluate, score confidence, decide whether a human must review
    7. persist the insight with full provenance, and audit the call

Step 1 is the load-bearing architectural decision: the model reads a curated,
PII-free, point-in-time view, not the CRM.  ADR-004 and docs/ai-architecture.md
give the argument in full; the short version is that an LLM given live access to
operational systems has the blast radius of an unaudited admin account.
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from common import data_platform
from common.config import get_settings
from common.errors import AIServiceError, NotFoundError
from common.middleware import current_correlation_id

from . import evaluation, prompts
from .guardrails import check_output, sanitise_input
from .providers import build_provider

log = logging.getLogger("ai.capabilities")
_settings = get_settings()

INSIGHT_TTL_HOURS = 24


# ---------------------------------------------------------------------------
# Grounding
# ---------------------------------------------------------------------------
GROUNDING_SQL = """
SELECT * FROM ACME_EDP.AI.V_CUSTOMER_AI_CONTEXT WHERE CUSTOMER_ID = ?
"""

SUPPORT_CONTEXT_SQL = """
SELECT CASE_ID, CASE_TYPE, PRIORITY, STATUS, OPENED_DATE, CSAT_SCORE, DESCRIPTION_EXCERPT
FROM ACME_EDP.AI.V_CUSTOMER_SUPPORT_CONTEXT
WHERE CUSTOMER_ID = ?
ORDER BY OPENED_DATE DESC
LIMIT 5
"""

CACHED_INSIGHT_SQL = """
SELECT INSIGHT_ID, GENERATED_TEXT, CONFIDENCE_SCORE, GROUNDEDNESS_SCORE, REVIEW_STATUS,
       MODEL_PROVIDER, MODEL_NAME, PROMPT_TEMPLATE_ID, PROMPT_VERSION, GENERATED_AT,
       GROUNDING_SOURCE_IDS, RECOMMENDED_ACTION, ACTION_PRIORITY, SENTIMENT_LABEL,
       SENTIMENT_SCORE
FROM ACME_EDP.AI.AI_CUSTOMER_INSIGHTS
WHERE CUSTOMER_BK = ? AND INSIGHT_TYPE = ? AND EXPIRES_AT > CURRENT_TIMESTAMP
ORDER BY GENERATED_AT DESC
LIMIT 1
"""


async def load_grounding(customer_id: str, include_support: bool = True) -> dict[str, Any]:
    """Assemble the facts the model is allowed to see.

    Note what is absent: name, e-mail, telephone, address, date of birth.  They
    are not filtered out here - they are not in AI.V_CUSTOMER_AI_CONTEXT at all,
    so no code path can leak them by omission of a filter.
    """
    # Read through the data platform's API, never by opening the warehouse.
    # See common/data_platform.py for why.
    rows = await data_platform.query(GROUNDING_SQL, customer_id)
    if not rows:
        raise NotFoundError(f"No Customer 360 record exists for '{customer_id}'.")
    r = rows[0]

    facts: dict[str, Any] = {
        "customerReference": customer_id,
        # The measurement windows are stated as facts and not left implicit
        # in field names. Two reasons: the model is told what "recent" means
        # instead of inferring it, and a window length quoted in the narrative
        # ("in the last 90 days") is then traceable to the grounding block like
        # any other figure.
        "recentActivityWindowDays": 90,
        "trailingPeriodDays": 365,
        "customerSegment": r.get("CUSTOMER_SEGMENT"),
        "valueTier": r.get("VALUE_TIER"),
        "tenureDays": _num(r.get("TENURE_DAYS")),
        "totalOrders": _num(r.get("TOTAL_ORDERS")),
        "totalNetRevenue": _num(r.get("TOTAL_NET_REVENUE")),
        "avgOrderValue": _num(r.get("AVG_ORDER_VALUE")),
        "orderFrequencyPerYear": _num(r.get("ORDER_FREQUENCY_PER_YEAR")),
        "daysSinceLastOrder": _num(r.get("DAYS_SINCE_LAST_ORDER")),
        "revenueLast365d": _num(r.get("REVENUE_LAST_365D")),
        "returnRate": _num(r.get("RETURN_RATE")),
        "primaryOrderChannel": r.get("PRIMARY_ORDER_CHANNEL"),
        "totalCases": _num(r.get("TOTAL_CASES")),
        "openCases": _num(r.get("OPEN_CASES")),
        "casesLast90d": _num(r.get("CASES_LAST_90D")),
        "avgCsat": _num(r.get("AVG_CSAT")),
        "topCaseType": r.get("TOP_CASE_TYPE"),
        "loyaltyTier": r.get("LOYALTY_TIER"),
        "loyaltyStatus": r.get("LOYALTY_STATUS"),
        "loyaltyPointsBalance": _num(r.get("LOYALTY_POINTS_BALANCE")),
        "interactionsLast90d": _num(r.get("INTERACTIONS_LAST_90D")),
        "negativeSignals90d": _num(r.get("NEGATIVE_SIGNALS_90D")),
        "engagementScore": _num(r.get("ENGAGEMENT_SCORE")),
        "orderTrendRatio": _num(r.get("ORDER_TREND_RATIO")),
        "revenueTrendRatio": _num(r.get("REVENUE_TREND_RATIO")),
        "slaBreaches": _num(r.get("SLA_BREACHES")),
        "churnProbability": _num(r.get("CHURN_PROBABILITY")),
        "churnRiskBand": r.get("CHURN_RISK_BAND"),
        "topDriver1": r.get("TOP_DRIVER_1"),
        "topDriver1Contribution": _num(r.get("TOP_DRIVER_1_CONTRIB")),
        "topDriver2": r.get("TOP_DRIVER_2"),
        "topDriver3": r.get("TOP_DRIVER_3"),
        "asOf": str(r.get("AS_OF_TIMESTAMP")),
    }

    injection_found = False
    if include_support:
        cases = await data_platform.query(SUPPORT_CONTEXT_SQL, customer_id)
        rendered = []
        for c in cases:
            clean, _redacted, injected = sanitise_input(c.get("DESCRIPTION_EXCERPT") or "")
            injection_found = injection_found or injected
            csat = c.get("CSAT_SCORE")
            rendered.append(
                f"{c.get('CASE_ID')} | {c.get('CASE_TYPE')} | {c.get('PRIORITY')} | "
                f"{c.get('STATUS')} | opened {c.get('OPENED_DATE')} | "
                f"CSAT {csat if csat is not None else 'n/a'} | {clean}")
        facts["recentSupportCases"] = rendered or ["none in the last 12 months"]

    facts["_injectionDetected"] = injection_found
    return facts


def _num(value):
    """Normalise a warehouse numeric for use as a prompt fact.

    NULL and NaN both become None so that ``render_facts`` writes
    "NOT AVAILABLE" - which the prompt rules tell the model to report honestly -
    instead of a number-shaped token it will repeat as fact.
    """
    import math
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return value
    if math.isnan(f) or math.isinf(f):
        return None
    return int(f) if f.is_integer() else round(f, 4)


# ---------------------------------------------------------------------------
# Generation
# ---------------------------------------------------------------------------
async def generate(capability: str, customer_id: str, *, question: str | None = None,
                   client_id: str = "unknown", subject: str = "unknown",
                   force_refresh: bool = False) -> dict[str, Any]:
    template = prompts.get_template(capability)
    correlation_id = current_correlation_id()
    request_id = uuid.uuid4().hex

    if not force_refresh:
        cached = await _cached_insight(customer_id, template.capability)
        if cached:
            cached["cached"] = True
            return cached

    facts = await load_grounding(customer_id)
    injection_detected = facts.pop("_injectionDetected", False)
    facts_block = prompts.render_facts(facts)

    knowledge_chunks = []
    knowledge_block = ""
    if capability.upper() in ("NEXT_BEST_ACTION", "GROUNDED_QA"):
        from .rag import format_context, retrieve  # noqa: PLC0415
        query = question or _retrieval_query(capability, facts)
        knowledge_chunks = await retrieve(query)
        knowledge_block = format_context(knowledge_chunks)

    user_prompt = template.user.format(
        facts=facts_block,
        approved_actions="\n".join(f"- {a['code']}: {a['description']}"
                                   for a in prompts.APPROVED_ACTIONS),
        knowledge=knowledge_block,
        question=question or "")

    provider = build_provider()
    try:
        completion = await provider.complete(
            template.system, user_prompt,
            max_tokens=template.max_output_tokens, temperature=template.temperature)
    except Exception as exc:                                     # noqa: BLE001
        await _audit(request_id, correlation_id, customer_id, client_id, subject, template,
                     provider_name=_settings.ai_provider, model=_settings.ai_model,
                     input_tokens=0, output_tokens=0, latency_ms=0, outcome="ERROR",
                     block_reason=str(exc)[:400])
        raise AIServiceError("The model provider did not return a usable response.") from exc

    grounding_text = facts_block + "\n" + knowledge_block
    guard = check_output(completion.text, grounding_text)
    metrics = evaluation.evaluate(completion.text, grounding_text, template.capability,
                                  forbidden_values=[])
    scores = {m.metric: m.score for m in metrics}
    confidence = _confidence(scores, facts, knowledge_chunks, guard.passed)

    outcome = "SUCCESS"
    if not guard.passed:
        outcome = "BLOCKED"
        log.warning("guardrail_block", extra={"findings": guard.findings,
                                              "customerRef": customer_id})

    review_status = _review_status(confidence, guard.passed, injection_detected,
                                  template.capability)

    insight_id = uuid.uuid4().hex
    payload = {
        "insightId": insight_id,
        "customerId": customer_id,
        "insightType": template.capability,
        "generatedText": completion.text if guard.passed else _degraded_text(template.capability),
        "structured": _parse_structured(template.capability, completion.text) if guard.passed else None,
        "grounding": {
            "factCount": len(facts),
            "sourceView": "ACME_EDP.AI.V_CUSTOMER_AI_CONTEXT",
            "knowledgeArticles": [c.article_id for c in knowledge_chunks],
            "asOf": facts.get("asOf"),
        },
        "model": {"provider": completion.provider, "name": completion.model,
                  "temperature": template.temperature,
                  "promptTemplateId": template.template_id,
                  "promptVersion": template.version},
        "quality": {"confidence": confidence, "groundedness": scores.get("GROUNDEDNESS"),
                    "relevance": scores.get("RELEVANCE"), "safety": scores.get("SAFETY"),
                    "guardrailPassed": guard.passed, "guardrailFindings": guard.findings,
                    "injectionDetectedInSource": injection_detected},
        "review": {"status": review_status,
                   "requiresHumanApproval": review_status == "PENDING_REVIEW"},
        "usage": {"inputTokens": completion.input_tokens,
                  "outputTokens": completion.output_tokens,
                  "latencyMs": completion.latency_ms},
        "correlationId": correlation_id,
        "generatedAt": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "cached": False,
    }

    await _persist_insight(payload, facts, knowledge_chunks, completion, template,
                           confidence, scores, review_status)
    await evaluation.persist(metrics, insight_id=insight_id)
    await _audit(request_id, correlation_id, customer_id, client_id, subject, template,
                 provider_name=completion.provider, model=completion.model,
                 input_tokens=completion.input_tokens, output_tokens=completion.output_tokens,
                 latency_ms=completion.latency_ms, outcome=outcome,
                 block_reason="; ".join(guard.findings)[:400] if guard.findings else None)
    return payload


def _retrieval_query(capability: str, facts: dict) -> str:
    if capability.upper() == "NEXT_BEST_ACTION":
        return (f"retention offer eligibility win-back "
                f"{facts.get('daysSinceLastOrder')} days since last order "
                f"loyalty {facts.get('loyaltyTier')} "
                f"open support case {facts.get('openCases')} "
                f"{facts.get('topCaseType') or ''}")
    return "customer policy"


def _confidence(scores: dict, facts: dict, chunks, guard_passed: bool) -> float:
    """Confidence is derived from things we can measure, not asserted by the model.

    A model's own stated confidence is not evidence.  These four are:
    groundedness of the output, completeness of the input, whether retrieval
    found anything, and whether the output passed the guardrails.
    """
    grounded = scores.get("GROUNDEDNESS", 0.0)
    populated = sum(1 for k, v in facts.items()
                    if not k.startswith("_") and v not in (None, "", []))
    completeness = min(1.0, populated / 20.0)
    retrieval = 1.0 if not chunks else min(1.0, max(c.score for c in chunks) / 0.4)
    base = 0.45 * grounded + 0.30 * completeness + 0.25 * retrieval
    return round(base * (1.0 if guard_passed else 0.3), 4)


def _review_status(confidence: float, guard_passed: bool, injection: bool,
                   capability: str) -> str:
    """Human-in-the-loop policy.

    Review is mandatory when the output could drive a customer-facing action, or
    when any signal is off.  Everything else is auto-approved so the queue stays
    small enough that reviewers actually read it - a review queue nobody reads is
    worse than no queue, because it manufactures the appearance of oversight.
    """
    if not guard_passed or injection:
        return "PENDING_REVIEW"
    if capability == "NEXT_BEST_ACTION":
        return "PENDING_REVIEW"
    if confidence < _settings.ai_human_review_threshold:
        return "PENDING_REVIEW"
    return "AUTO_APPROVED"


def _degraded_text(capability: str) -> str:
    return ("An automated insight could not be produced for this customer because the "
            "generated response failed the platform's grounding checks. The underlying "
            "analytics and churn score are unaffected and are available in the response.")


def _parse_structured(capability: str, text: str) -> dict | None:
    if capability not in ("NEXT_BEST_ACTION", "SENTIMENT"):
        return None
    try:
        start, end = text.index("{"), text.rindex("}") + 1
        parsed = json.loads(text[start:end])
    except (ValueError, json.JSONDecodeError):
        return None
    if capability == "NEXT_BEST_ACTION":
        allowed = {a["code"] for a in prompts.APPROVED_ACTIONS}
        if parsed.get("action") not in allowed:
            # A model that invents an action code is a governance failure, not a
            # formatting one: it means the constraint was not enforced.
            return {"action": "NO_ACTION", "priority": "LOW",
                    "justification": "The recommended action was not on the approved list "
                                     "and has been suppressed.",
                    "suppressedAction": parsed.get("action")}
    return parsed


# ---------------------------------------------------------------------------
# Persistence and audit
# ---------------------------------------------------------------------------
async def _cached_insight(customer_id: str, capability: str) -> dict | None:
    """Serve a recent insight and not paying for a new generation.

    The TTL is short (24h) because the underlying analytics are rebuilt daily:
    an insight that outlives its grounding data is a confident statement about
    a customer who has since changed.
    """
    try:
        rows = await data_platform.query(CACHED_INSIGHT_SQL, customer_id, capability)
    except Exception:                                            # noqa: BLE001
        return None
    if not rows:
        return None
    r = rows[0]
    return {
        "insightId": r["INSIGHT_ID"], "customerId": customer_id, "insightType": capability,
        "generatedText": r["GENERATED_TEXT"],
        "structured": ({"action": r["RECOMMENDED_ACTION"], "priority": r["ACTION_PRIORITY"]}
                       if r.get("RECOMMENDED_ACTION") else
                       ({"label": r["SENTIMENT_LABEL"], "score": r["SENTIMENT_SCORE"]}
                        if r.get("SENTIMENT_LABEL") else None)),
        "grounding": {"knowledgeArticles":
                      (r.get("GROUNDING_SOURCE_IDS") or "").split(",")
                      if r.get("GROUNDING_SOURCE_IDS") else []},
        "model": {"provider": r["MODEL_PROVIDER"], "name": r["MODEL_NAME"],
                  "promptTemplateId": r["PROMPT_TEMPLATE_ID"],
                  "promptVersion": r["PROMPT_VERSION"]},
        "quality": {"confidence": r["CONFIDENCE_SCORE"], "groundedness": r["GROUNDEDNESS_SCORE"]},
        "review": {"status": r["REVIEW_STATUS"],
                   "requiresHumanApproval": r["REVIEW_STATUS"] == "PENDING_REVIEW"},
        "generatedAt": str(r["GENERATED_AT"]),
    }


async def _persist_insight(payload, facts, chunks, completion, template, confidence, scores,
                           review_status) -> None:
    """Best effort.  A persistence failure must never fail the caller's request -
    the insight has already been produced and validated; losing the audit copy is
    an operations problem, not a client-facing one.  It is logged at WARNING and
    picked up by the alert on AI_REQUEST_AUDIT vs AI_CUSTOMER_INSIGHTS drift."""
    try:
        structured = payload.get("structured") or {}
        now = datetime.now(UTC).replace(tzinfo=None).isoformat(sep=" ")
        await data_platform.write("ai_insight", [[
            payload["insightId"], payload["customerId"], template.capability,
            payload["generatedText"], structured.get("action"), structured.get("priority"),
            structured.get("label"), structured.get("score"),
            json.dumps({k: v for k, v in facts.items() if not k.startswith("_")}, default=str),
            ",".join(c.article_id for c in chunks), template.template_id, template.version,
            completion.provider, completion.model, template.temperature,
            completion.input_tokens, completion.output_tokens, completion.latency_ms,
            confidence, scores.get("GROUNDEDNESS"), review_status, True, now,
            (datetime.now(UTC).replace(tzinfo=None)
             + timedelta(hours=INSIGHT_TTL_HOURS)).isoformat(sep=" "),
            payload["correlationId"]]])
    except Exception as exc:                                     # noqa: BLE001
        log.warning("insight_persist_failed: %s", exc)


# Indicative unit prices for cost attribution.  Not a price list - a placeholder
# so the audit table carries a cost dimension from day one.
_COST_PER_1K = {"local": 0.0, "cortex": 0.0015, "openai": 0.0025, "bedrock": 0.0030}


async def _audit(request_id, correlation_id, customer_id, client_id, subject, template,
                 provider_name, model, input_tokens, output_tokens, latency_ms, outcome,
                 block_reason=None) -> None:
    """Every generative call is audited - successes, blocks and errors alike.

    An audit trail that only records successes cannot answer the two questions
    that get asked after an incident: what did we refuse, and what did we spend.
    """
    try:
        rate = _COST_PER_1K.get(provider_name, 0.0)
        cost = round((input_tokens + output_tokens) / 1000.0 * rate, 6)
        await data_platform.write("ai_audit", [[
            request_id, correlation_id, customer_id, client_id, subject, template.capability,
            template.template_id, template.version, provider_name, model, input_tokens,
            output_tokens, cost, latency_ms, outcome, block_reason,
            _settings.ai_pii_redaction,
            datetime.now(UTC).replace(tzinfo=None).isoformat(sep=" ")]])
    except Exception as exc:                                     # noqa: BLE001
        log.warning("audit_write_failed: %s", exc)
