%dw 2.0
output application/json skipNullOn="everywhere"

/*
 * GET /customers/{customerId}/insights
 *
 * The churn score and the generated narrative are returned together but degrade
 * independently: the score comes from the warehouse and the narrative from the
 * model, and one being unavailable is no reason to withhold the other.
 */
var src = vars.processResponse
---
{
    customerId: src.customerId,
    churnRisk:  src.churnRisk,
    insights: {
        generated: ((src.aiInsights.insights default []) map (i) -> {
            "type":                i.insightType,
            text:                  i.generatedText,
            structured:            i.structured,
            confidence:            i.quality.confidence,
            requiresHumanApproval: i.review.requiresHumanApproval default false,
            reviewStatus:          i.review.status,
            generatedBy: { provider: i.model.provider, model: i.model.name },
            sources:               i.grounding.knowledgeArticles default [],
            generatedAt:           i.generatedAt,
            cached:                i.cached default false,
            disclaimer: "AI-generated from Acme's own customer data. Verify before acting on it."
        }),
        unavailable: src.aiInsights.failures default []
    },
    meta: {
        correlationId:  correlationId,
        partial:        src.partial default false,
        degradedFields: (src.degradedFields default []) map $.field
    }
}
