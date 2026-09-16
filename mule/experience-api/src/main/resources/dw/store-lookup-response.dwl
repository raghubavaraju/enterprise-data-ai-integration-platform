%dw 2.0
output application/json skipNullOn="everywhere"

/*
 * Store Associate Experience layer - shaping for GET /associate/customers/
 * {customerId}/lookup.
 *
 * This is not customer-360-response.dwl with fields removed - it is a
 * separate transform because the two consumers can drift independently. The
 * service-desk app deciding it needs one more analytics field tomorrow should
 * never risk changing what a store associate sees on a shared handheld.
 *
 * Contact fields (e-mail, phone, birth date) are not read from vars.processResponse
 * at all here - not masked, absent. Only fullName is ever considered, and only
 * to become a masked display name, because this application's registered
 * client is never issued pii:read (see mule/common - the OAuth client
 * registry mirrors services/common/security.py).
 */

fun maskFamilyName(name) = do {
    var parts = (name default "") splitBy " "
    ---
    if (name == null) null
    else if (sizeOf(parts) == 1) name
    else parts[0] ++ " " ++ ((parts[1 to -1] map ($[0] ++ ("*" repeat 3))) joinBy " ")
}

var src = vars.processResponse
var profile = src.profile default {}
var analytics = src.analytics default {}
---
{
    customerId: src.customerId,
    displayName: maskFamilyName(profile.fullName),
    segment: profile.segment,
    status: profile.status,
    // A yes/no signal for "give this customer extra attention", not the raw
    // value tier the decision was derived from.
    vip: (profile.segment == "PREMIUM") or (analytics.valueTier == "HIGH"),
    loyalty: src.loyalty,
    meta: {
        masked: true,
        correlationId: correlationId,
        partial: src.partial default false,
        degradedFields: (src.degradedFields default []) map $.field,
        dataCompletenessScore: src.dataQuality.completenessScore,
        asOf: src.dataQuality.asOf
    }
}
