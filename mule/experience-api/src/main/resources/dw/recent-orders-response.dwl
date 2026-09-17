%dw 2.0
output application/json skipNullOn="everywhere"

/*
 * Store Associate Experience layer - shaping for GET /associate/customers/
 * {customerId}/recent-orders.
 *
 * Field renaming happens here, at this edge, and nowhere upstream: the
 * process and system layers keep calling it orderStatus and totalUnits
 * because that is what the warehouse view calls it. This consumer calls the
 * same facts status and itemCount because that is what a return conversation
 * at the counter calls them. Two names for one fact is the cost of shaping a
 * payload per consumer, and it is a lower cost than making every consumer
 * agree on one vocabulary before either of them can ship.
 */

var src = vars.processResponse
---
{
    customerId: src.customerId,
    orders: (src.orders default []) map (o) -> {
        orderId: o.orderId,
        orderDate: o.orderDate,
        status: o.orderStatus,
        netAmount: o.netAmount,
        itemCount: o.totalUnits
    },
    meta: {
        partial: src.partial default false,
        degradedFields: (src.degradedFields default []) map $.field,
        correlationId: correlationId
    }
}
