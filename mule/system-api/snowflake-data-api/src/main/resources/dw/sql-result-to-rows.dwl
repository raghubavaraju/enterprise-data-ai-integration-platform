%dw 2.0
output application/json

/*
 * Snowflake's SQL API returns a column-metadata block plus rows as arrays of
 * strings. Turn that into an array of typed objects, once, here - so that no
 * flow downstream has to know the wire format.
 *
 * Types come from resultSetMetaData.rowType. Coercing on the client rather than
 * trusting string values matters: "0.3988" and 0.3988 behave differently the
 * moment a consumer compares, sorts or sums them, and the bug surfaces far from
 * its cause.
 */

var meta = (vars.sqlResponse.resultSetMetaData.rowType default [])
var names = meta map $.name
var types = meta map $."type"

fun coerce(value, snowType) =
    if (value == null) null
    else snowType match {
        case "FIXED"  -> value as Number
        case "REAL"   -> value as Number
        case "BOOLEAN"-> value as Boolean
        else          -> value
    }
---
(vars.sqlResponse.data default []) map (row) -> (
    (names map (name, i) -> { (name): coerce(row[i], types[i]) })
        reduce ((item, acc = {}) -> acc ++ item)
)
