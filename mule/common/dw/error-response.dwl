%dw 2.0
output application/json
/*
 * Canonical error payload. Referenced by the global error handler for every
 * status code, so the shape cannot drift between error classes.
 *
 * Deliberately absent: error.detailedDescription, the exception, any downstream
 * body. Those go to the log, keyed by correlationId. What a client gets is a
 * stable code it can branch on, a safe message, and the id that lets support
 * find everything else.
 */
---
{
    errorCode:     vars.errorCode,
    message:       vars.errorCode match {
                       case "PLATFORM:VALIDATION_ERROR"      -> (error.description default "The request failed validation.")
                       case "PLATFORM:UNAUTHORIZED"          -> "Authentication is required."
                       case "PLATFORM:FORBIDDEN"             -> "The token does not carry the scope required for this operation."
                       case "PLATFORM:RESOURCE_NOT_FOUND"    -> "The requested resource does not exist."
                       case "PLATFORM:RATE_LIMIT_EXCEEDED"   -> "Rate limit exceeded."
                       case "PLATFORM:DOWNSTREAM_UNAVAILABLE"-> "A downstream system is unavailable."
                       case "PLATFORM:DOWNSTREAM_TIMEOUT"    -> "A downstream system did not respond in time."
                       case "DATA:QUERY_FAILED"              -> "The analytical data platform rejected or failed the query."
                       case "AI:GENERATION_FAILED"           -> "The AI service could not produce a grounded response."
                       else                                  -> "An unexpected error occurred."
                   },
    correlationId: correlationId,
    timestamp:     now() as String {format: "yyyy-MM-dd'T'HH:mm:ss'Z'"},
    path:          attributes.requestPath default "",
    retryable:     vars.retryable default false,
    details:       vars.errorDetails default []
}
