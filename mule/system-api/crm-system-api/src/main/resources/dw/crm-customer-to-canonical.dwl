%dw 2.0
output application/json skipNullOn="everywhere"

/*
 * CRM record -> canonical Acme customer.
 *
 * This file is the boundary. Everything above it in the estate speaks the
 * canonical vocabulary; everything below it speaks CRM. Concretely:
 *
 *   CRM field          canonical field     note
 *   -----------------  ------------------  ----------------------------------
 *   CustomerNumber     customerId          the CRM's name for the business key
 *   GivenName          firstName
 *   FamilyName         lastName
 *   EmailAddr          email               lower-cased and trimmed here, once
 *   PhoneNbr           phone               digits and leading + only
 *   DOB                birthDate           dd/MM/yyyy in the CRM, ISO for us
 *   SegmentCd          segment             coded values expanded to the
 *                                          enterprise vocabulary
 *   OptInFlag          marketingOptIn      Y/N -> boolean
 *   RecStatus          status              A/I/C -> ACTIVE/INACTIVE/CLOSED
 *
 * Doing this once, here, makes "replace the CRM" a change to one
 * application. Doing it in each consumer is what makes it a programme.
 */

var src = vars.crmCustomer

fun expandSegment(code) = code match {
    case "CON" -> "CONSUMER"
    case "SMB" -> "SMALL_BUSINESS"
    case "PRM" -> "PREMIUM"
    else       -> "UNCLASSIFIED"
}

fun expandStatus(code) = code match {
    case "A" -> "ACTIVE"
    case "I" -> "INACTIVE"
    case "C" -> "CLOSED"
    else     -> "UNKNOWN"
}

fun isoDate(ddmmyyyy) =
    if (ddmmyyyy == null) null
    else (ddmmyyyy as Date {format: "dd/MM/yyyy"}) as String {format: "yyyy-MM-dd"}
---
{
    customerId:       src.CustomerNumber,
    firstName:        trim(src.GivenName default ""),
    lastName:         trim(src.FamilyName default ""),
    email:            lower(trim(src.EmailAddr default "")),
    phone:            (src.PhoneNbr default "") replace /[^0-9+]/ with "",
    birthDate:        isoDate(src.DOB),
    segment:          expandSegment(src.SegmentCd),
    preferredChannel: upper(src.PrefChannel default "WEB"),
    marketingOptIn:   (src.OptInFlag default "N") == "Y",
    status:           expandStatus(src.RecStatus),
    /* The CRM emits local time with no offset. Stamping UTC here and not
       downstream means the ambiguity is resolved at the only place that knows
       which timezone the CRM runs in. */
    createdAt:        if (src.CreatedTs == null) null
                      else (src.CreatedTs ++ "Z"),
    sourceSystem:     "CRM"
}
