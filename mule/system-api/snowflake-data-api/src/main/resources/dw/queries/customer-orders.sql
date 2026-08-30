-- Statement executed by GET /customers/{customerId}/orders.
-- LIMIT and OFFSET are bind parameters, not interpolated values: an unbounded
-- collection endpoint is a denial-of-service vector against the warehouse.
SELECT ORDER_ID, ORDER_DATE, ORDER_STATUS, CHANNEL, CURRENCY_CODE,
       ORDER_AMOUNT, DISCOUNT_AMOUNT, SHIPPING_AMOUNT, NET_AMOUNT,
       LINE_COUNT, TOTAL_UNITS
FROM ACME_EDP.ANALYTICS.V_CUSTOMER_ORDERS_API
WHERE CUSTOMER_ID = ?
ORDER BY ORDER_DATE DESC
LIMIT ? OFFSET ?
