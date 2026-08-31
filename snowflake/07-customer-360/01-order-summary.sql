-- =============================================================================
-- 07-01  ANALYTICS.CUSTOMER_ORDER_SUMMARY      [portable]
-- =============================================================================
-- Revenue definition, stated once and reused everywhere:
--   revenue = NET_AMOUNT of orders in (COMPLETED, SHIPPED)
--   CANCELLED and RETURNED orders are counted for behaviour, never for revenue.
-- Getting this wrong in one place and right in another is how two dashboards
-- end up disagreeing about the same customer, so it is centralised here and
-- CUSTOMER_360 reads it and not recomputing it.
-- =============================================================================

DELETE FROM ACME_EDP.ANALYTICS.CUSTOMER_ORDER_SUMMARY;

INSERT INTO ACME_EDP.ANALYTICS.CUSTOMER_ORDER_SUMMARY
WITH base AS (
    SELECT o.*, (o.ORDER_STATUS IN ('COMPLETED','SHIPPED')) AS IS_REVENUE
    FROM ACME_EDP.CORE.SALES_ORDER o
    WHERE o.CUSTOMER_BK IS NOT NULL
),
cat AS (
    SELECT o.CUSTOMER_BK, COUNT(DISTINCT p.CATEGORY) AS DISTINCT_CATEGORIES
    FROM ACME_EDP.CORE.SALES_ORDER o
    JOIN ACME_EDP.CORE.SALES_ORDER_ITEM i ON i.ORDER_BK = o.ORDER_BK
    JOIN ACME_EDP.CORE.PRODUCT p          ON p.PRODUCT_BK = i.PRODUCT_BK
    GROUP BY o.CUSTOMER_BK
),
chan AS (
    SELECT CUSTOMER_BK, CHANNEL AS PRIMARY_CHANNEL
    FROM (
        SELECT CUSTOMER_BK, CHANNEL, COUNT(*) AS N,
               ROW_NUMBER() OVER (PARTITION BY CUSTOMER_BK ORDER BY COUNT(*) DESC, CHANNEL) AS RN
        FROM ACME_EDP.CORE.SALES_ORDER
        WHERE CUSTOMER_BK IS NOT NULL
        GROUP BY CUSTOMER_BK, CHANNEL
    ) t
    WHERE RN = 1
),
agg AS (
    SELECT
        CUSTOMER_BK,
        MIN(ORDER_DATE)                                                   AS FIRST_ORDER_DATE,
        MAX(ORDER_DATE)                                                   AS LAST_ORDER_DATE,
        COUNT(*)                                                          AS TOTAL_ORDERS,
        SUM(CASE WHEN ORDER_STATUS = 'COMPLETED' THEN 1 ELSE 0 END)       AS COMPLETED_ORDERS,
        SUM(CASE WHEN ORDER_STATUS = 'CANCELLED' THEN 1 ELSE 0 END)       AS CANCELLED_ORDERS,
        SUM(CASE WHEN ORDER_STATUS = 'RETURNED'  THEN 1 ELSE 0 END)       AS RETURNED_ORDERS,
        SUM(CASE WHEN IS_REVENUE THEN NET_AMOUNT ELSE 0 END)              AS TOTAL_NET_REVENUE,
        AVG(CASE WHEN IS_REVENUE THEN NET_AMOUNT END)                     AS AVG_ORDER_VALUE,
        MAX(CASE WHEN IS_REVENUE THEN NET_AMOUNT END)                     AS MAX_ORDER_VALUE,
        SUM(CASE WHEN ORDER_DATE >= CURRENT_DATE - 90  THEN 1 ELSE 0 END) AS ORDERS_LAST_90D,
        SUM(CASE WHEN ORDER_DATE >= CURRENT_DATE - 90 AND IS_REVENUE
                 THEN NET_AMOUNT ELSE 0 END)                              AS REVENUE_LAST_90D,
        SUM(CASE WHEN ORDER_DATE >= CURRENT_DATE - 365 THEN 1 ELSE 0 END) AS ORDERS_LAST_365D,
        SUM(CASE WHEN ORDER_DATE >= CURRENT_DATE - 365 AND IS_REVENUE
                 THEN NET_AMOUNT ELSE 0 END)                              AS REVENUE_LAST_365D
    FROM base
    GROUP BY CUSTOMER_BK
)
SELECT
    a.CUSTOMER_BK,
    a.FIRST_ORDER_DATE,
    a.LAST_ORDER_DATE,
    DATEDIFF(day, a.LAST_ORDER_DATE, CURRENT_DATE)                        AS DAYS_SINCE_LAST_ORDER,
    a.TOTAL_ORDERS, a.COMPLETED_ORDERS, a.CANCELLED_ORDERS, a.RETURNED_ORDERS,
    ROUND(a.TOTAL_NET_REVENUE, 2)                                         AS TOTAL_NET_REVENUE,
    ROUND(COALESCE(a.AVG_ORDER_VALUE, 0), 2)                              AS AVG_ORDER_VALUE,
    ROUND(COALESCE(a.MAX_ORDER_VALUE, 0), 2)                              AS MAX_ORDER_VALUE,
    a.ORDERS_LAST_90D, ROUND(a.REVENUE_LAST_90D, 2)                       AS REVENUE_LAST_90D,
    a.ORDERS_LAST_365D, ROUND(a.REVENUE_LAST_365D, 2)                     AS REVENUE_LAST_365D,
    -- Annualised frequency over the observed relationship, floored at 30 days so
    -- a customer who joined last week does not appear to order 300 times a year.
    ROUND(a.TOTAL_ORDERS * 365.0 /
          GREATEST(DATEDIFF(day, a.FIRST_ORDER_DATE, CURRENT_DATE), 30), 4)
                                                                          AS ORDER_FREQUENCY_PER_YEAR,
    COALESCE(c.DISTINCT_CATEGORIES, 0)                                    AS DISTINCT_CATEGORIES,
    ch.PRIMARY_CHANNEL,
    ROUND(a.RETURNED_ORDERS * 1.0 / NULLIF(a.TOTAL_ORDERS, 0), 4)         AS RETURN_RATE,
    CURRENT_DATE                                                          AS AS_OF_DATE,
    CURRENT_TIMESTAMP                                                     AS _LOADED_AT
FROM agg a
LEFT JOIN cat  c  ON c.CUSTOMER_BK  = a.CUSTOMER_BK
LEFT JOIN chan ch ON ch.CUSTOMER_BK = a.CUSTOMER_BK;
