%dw 2.0
output application/json skipNullOn="everywhere"

/*
 * POST /customers/{customerId}/ai-analysis
 *
 * Trim provenance to what a client application needs in order to decide two
 * things: may it display this text, and does a human still have to approve it.
 *
 * The full provenance - grounding snapshot, prompt template and version, token
 * counts, groundedness score - stays in AI.AI_CUSTOMER_INSIGHTS. Publishing the
 * prompt version to a client would make it part of the API contract, which is
 * the last thing you want when prompts are versioned weekly.
 */
var src = vars.aiResponse
---
{
    customerId:            src.customerId,
    "type":                src.insightType,
    text:                  src.generatedText,
    structured:            src.structured,
    confidence:            src.quality.confidence,
    requiresHumanApproval: src.review.requiresHumanApproval default false,
    reviewStatus:          src.review.status,
    generatedBy: { provider: src.model.provider, model: src.model.name },
    sources:               src.grounding.knowledgeArticles default [],
    generatedAt:           src.generatedAt,
    cached:                src.cached default false,
    disclaimer: "AI-generated from Acme's own customer data. Verify before acting on it.",
    meta: {
        correlationId:    correlationId,
        idempotentReplay: src.idempotentReplay default false
    }
}
