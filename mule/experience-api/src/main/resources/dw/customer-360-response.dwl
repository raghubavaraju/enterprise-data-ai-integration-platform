%dw 2.0
output application/json skipNullOn="everywhere"

/*
 * Experience-layer shaping for GET /customers/{customerId}/360.
 *
 * Two jobs:
 *   1. present the process-layer object in the shape the service-desk app wants
 *   2. mask direct identifiers unless the caller holds pii:read
 *
 * The masking decision comes from vars.maySeePii, which is derived from the
 * token API Manager already validated.  It is never a request parameter: a
 * client that can ask for unmasked data by adding ?mask=false does not have an
 * access control, it has a suggestion.
 *
 * Masking rules follow docs/data-governance.md:
 *   e-mail       first character + domain
 *   phone        last four digits
 *   name         given name kept, family name masked - an agent has to be able
 *                to address the customer, and masking the whole name is how
 *                masking ends up switched off in production
 *   birth date   generalised to year (quasi-identifier)
 */

fun maskEmail(email) =
    if (email == null or !(email contains "@")) email
    else email[0] ++ ("*" repeat 9) ++ "@" ++ (email splitBy "@")[1]

fun maskPhone(phone) =
    if (phone == null) null
    else "***-***-" ++ (phone replace /[^0-9]/ with "")[-4 to -1]

fun maskFamilyName(name) = do {
    var parts = (name default "") splitBy " "
    ---
    if (name == null) null
    else if (sizeOf(parts) == 1) name
    else parts[0] ++ " " ++ ((parts[1 to -1] map ($[0] ++ ("*" repeat 3))) joinBy " ")
}

fun maskBirthDate(d) = if (d == null) null else (d as String)[0 to 3] ++ "-**-**"

var src = vars.processResponse
var pii = vars.maySeePii default false
var profile = src.profile default {}
---
{
    customerId: src.customerId,

    profile: {
        fullName:         if (pii) profile.fullName  else maskFamilyName(profile.fullName),
        email:            if (pii) profile.email     else maskEmail(profile.email),
        phone:            if (pii) profile.phone     else maskPhone(profile.phone),
        birthDate:        if (pii) profile.birthDate else maskBirthDate(profile.birthDate),
        segment:          profile.segment,
        status:           profile.status,
        preferredChannel: profile.preferredChannel,
        marketingOptIn:   profile.marketingOptIn,
        customerSince:    profile.customerSince,
        tenureDays:       profile.tenureDays,
        location:         profile.location,
        ("_masked": true) if (not pii),
        ("_maskedFields": ["birthDate", "email", "fullName", "phone"]) if (not pii)
    },

    orders:    src.orders  default [],
    support:   src.support default [],
    loyalty:   src.loyalty,
    analytics: src.analytics,
    churnRisk: src.churnRisk,

    aiInsights: if (src.aiInsights == null) null else {
        generated: (src.aiInsights.insights default []) map (i) -> {
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
            /* Shown verbatim by the UI next to any generated text. Not optional. */
            disclaimer: "AI-generated from Acme's own customer data. Verify before acting on it."
        },
        unavailable: src.aiInsights.failures default []
    },

    meta: {
        correlationId:         correlationId,
        partial:               src.partial default false,
        /* The experience layer publishes field names only; the dependency and the
           underlying error stay internal. A client needs to know that loyalty
           data is missing - not that the loyalty platform returned 503. */
        degradedFields:        (src.degradedFields default []) map $.field,
        dataCompletenessScore: src.dataQuality.completenessScore,
        contributingSources:   src.dataQuality.contributingSources,
        asOf:                  src.dataQuality.asOf
    }
}
