-- =============================================================================
-- 07-03  ANALYTICS.CUSTOMER_360      [portable]
-- =============================================================================
-- The unified customer view.  Every derived attribute below is *deterministic
-- and explainable* - no black boxes - because these values are shown to service
-- agents and are used to ground AI generation.  An unexplainable number in a
-- customer-facing context is a liability, not a feature.
--
-- Derivations, stated explicitly:
--
--   TENURE_DAYS              days since the earliest of CRM creation and first
--                            order.  Some customers transacted before the CRM
--                            record existed; using CRM alone understates tenure.
--
--   ENGAGEMENT_SCORE         defined once in 07-02 and read here.  Weighted,
--                            capped, explainable; weights are a documented
--                            business assumption - see docs/data-architecture.md.
--
--   CUSTOMER_LIFETIME_VALUE  realised value = historical net revenue on
--                            recognised orders.  Deliberately *not* a
--                            prediction: CLV and predicted CLV are different
--                            numbers and conflating them misleads the business.
--
--   PREDICTED_CLV_12M        simple, transparent projection:
--                            AOV x annualised frequency x expected retention,
--                            where expected retention = 1 - churn probability.
--                            Labelled "predicted" everywhere it appears.
--
--   DATA_COMPLETENESS_SCORE  percentage of the eight profile attributes that are
--                            populated.  Surfaced through the API so a consumer
--                            can tell "no support history" from "support system
--                            was unavailable".
-- =============================================================================

DELETE FROM ACME_EDP.ANALYTICS.CUSTOMER_360;

INSERT INTO ACME_EDP.ANALYTICS.CUSTOMER_360
WITH cust AS (
    SELECT * FROM ACME_EDP.CORE.CUSTOMER WHERE IS_CURRENT = TRUE
),
addr AS (
    SELECT CUSTOMER_BK, CITY, STATE, COUNTRY
    FROM (
        SELECT CUSTOMER_BK, CITY, STATE, COUNTRY,
               ROW_NUMBER() OVER (PARTITION BY CUSTOMER_BK
                                  ORDER BY CASE WHEN IS_PRIMARY THEN 0 ELSE 1 END,
                                           ADDRESS_TYPE) AS RN
        FROM ACME_EDP.CORE.CUSTOMER_ADDRESS
    ) a WHERE RN = 1
),
churn AS (
    SELECT CUSTOMER_BK, CHURN_PROBABILITY
    FROM ACME_EDP.AI.CUSTOMER_CHURN_SCORE
    QUALIFY ROW_NUMBER() OVER (PARTITION BY CUSTOMER_BK ORDER BY SCORE_DATE DESC) = 1
)
SELECT
    c.CUSTOMER_BK,
    c.CUSTOMER_SK,
    c.MASTER_CUSTOMER_ID,
    c.FULL_NAME,
    c.EMAIL,
    c.PHONE,
    c.BIRTH_DATE,
    c.CUSTOMER_SEGMENT,
    c.PREFERRED_CHANNEL,
    c.MARKETING_OPT_IN,
    c.STATUS                                                            AS CUSTOMER_STATUS,
    LEAST(CAST(c.SOURCE_CREATED_AT AS DATE),
          COALESCE(o.FIRST_ORDER_DATE, CAST(c.SOURCE_CREATED_AT AS DATE))) AS CUSTOMER_SINCE,
    DATEDIFF(day,
             LEAST(CAST(c.SOURCE_CREATED_AT AS DATE),
                   COALESCE(o.FIRST_ORDER_DATE, CAST(c.SOURCE_CREATED_AT AS DATE))),
             CURRENT_DATE)                                              AS TENURE_DAYS,
    a.CITY, a.STATE, a.COUNTRY,

    COALESCE(o.TOTAL_ORDERS, 0)                                         AS TOTAL_ORDERS,
    COALESCE(o.TOTAL_NET_REVENUE, 0)                                    AS TOTAL_NET_REVENUE,
    COALESCE(o.AVG_ORDER_VALUE, 0)                                      AS AVG_ORDER_VALUE,
    COALESCE(o.ORDER_FREQUENCY_PER_YEAR, 0)                             AS ORDER_FREQUENCY_PER_YEAR,
    o.LAST_ORDER_DATE,
    o.DAYS_SINCE_LAST_ORDER,
    COALESCE(o.REVENUE_LAST_365D, 0)                                    AS REVENUE_LAST_365D,
    COALESCE(o.RETURN_RATE, 0)                                          AS RETURN_RATE,
    o.PRIMARY_CHANNEL                                                   AS PRIMARY_ORDER_CHANNEL,

    COALESCE(s.TOTAL_CASES, 0)                                          AS TOTAL_CASES,
    COALESCE(s.OPEN_CASES, 0)                                           AS OPEN_CASES,
    COALESCE(s.CASES_LAST_90D, 0)                                       AS CASES_LAST_90D,
    s.AVG_CSAT,
    s.AVG_RESOLUTION_HOURS,
    s.TOP_CASE_TYPE,

    l.LOYALTY_ACCOUNT_BK,
    COALESCE(l.TIER, 'NONE')                                            AS LOYALTY_TIER,
    COALESCE(l.STATUS, 'NOT_ENROLLED')                                  AS LOYALTY_STATUS,
    COALESCE(l.POINTS_BALANCE, 0)                                       AS LOYALTY_POINTS_BALANCE,
    l.ENROLLED_AT                                                       AS LOYALTY_ENROLLED_AT,
    DATEDIFF(day, l.LAST_ACTIVITY_AT, CURRENT_DATE)                     AS DAYS_SINCE_LOYALTY_ACTIVITY,

    COALESCE(e.INTERACTIONS_LAST_90D, 0)                                AS INTERACTIONS_LAST_90D,
    COALESCE(e.NEGATIVE_SIGNALS_90D, 0)                                 AS NEGATIVE_SIGNALS_90D,

    -- Single definition, computed in 07-02 and reused here (never re-derived).
    COALESCE(e.ENGAGEMENT_SCORE, 0)                                     AS ENGAGEMENT_SCORE,

    ROUND(COALESCE(o.TOTAL_NET_REVENUE, 0), 2)                          AS CUSTOMER_LIFETIME_VALUE,
    ROUND(COALESCE(o.AVG_ORDER_VALUE, 0)
          * COALESCE(o.ORDER_FREQUENCY_PER_YEAR, 0)
          * (1 - COALESCE(ch.CHURN_PROBABILITY, 0.25)), 2)              AS PREDICTED_CLV_12M,
    CASE
        WHEN COALESCE(o.TOTAL_NET_REVENUE, 0) >= 2000 THEN 'HIGH'
        WHEN COALESCE(o.TOTAL_NET_REVENUE, 0) >= 500  THEN 'MEDIUM'
        ELSE 'LOW'
    END                                                                 AS VALUE_TIER,

    ROUND(100.0 * (
        (CASE WHEN c.EMAIL             IS NOT NULL THEN 1 ELSE 0 END) +
        (CASE WHEN c.PHONE             IS NOT NULL AND c.PHONE <> '' THEN 1 ELSE 0 END) +
        (CASE WHEN c.BIRTH_DATE        IS NOT NULL THEN 1 ELSE 0 END) +
        (CASE WHEN a.CITY              IS NOT NULL THEN 1 ELSE 0 END) +
        (CASE WHEN c.CUSTOMER_SEGMENT  IS NOT NULL THEN 1 ELSE 0 END) +
        (CASE WHEN o.CUSTOMER_BK       IS NOT NULL THEN 1 ELSE 0 END) +
        (CASE WHEN l.CUSTOMER_BK       IS NOT NULL THEN 1 ELSE 0 END) +
        (CASE WHEN s.CUSTOMER_BK       IS NOT NULL THEN 1 ELSE 0 END)
    ) / 8.0, 2)                                                         AS DATA_COMPLETENESS_SCORE,

    -- Which source systems actually contributed to this row.  Consumers need to
    -- distinguish "absent" from "not collected" from "system unavailable".
    'CRM' ||
    CASE WHEN o.CUSTOMER_BK IS NOT NULL THEN ',OMS'     ELSE '' END ||
    CASE WHEN s.CUSTOMER_BK IS NOT NULL THEN ',SUPPORT' ELSE '' END ||
    CASE WHEN l.CUSTOMER_BK IS NOT NULL THEN ',LOYALTY' ELSE '' END ||
    CASE WHEN e.CUSTOMER_BK IS NOT NULL THEN ',ENGAGEMENT' ELSE '' END  AS CONTRIBUTING_SOURCES,

    CURRENT_TIMESTAMP                                                   AS AS_OF_TIMESTAMP,
    c._BATCH_ID,
    c._CORRELATION_ID,
    CURRENT_TIMESTAMP                                                   AS _LOADED_AT
FROM cust c
LEFT JOIN ACME_EDP.ANALYTICS.CUSTOMER_ORDER_SUMMARY      o  ON o.CUSTOMER_BK = c.CUSTOMER_BK
LEFT JOIN ACME_EDP.ANALYTICS.CUSTOMER_SUPPORT_SUMMARY    s  ON s.CUSTOMER_BK = c.CUSTOMER_BK
LEFT JOIN ACME_EDP.ANALYTICS.CUSTOMER_ENGAGEMENT_SUMMARY e  ON e.CUSTOMER_BK = c.CUSTOMER_BK
LEFT JOIN ACME_EDP.CORE.LOYALTY_ACCOUNT                  l  ON l.CUSTOMER_BK = c.CUSTOMER_BK
LEFT JOIN addr                                           a  ON a.CUSTOMER_BK = c.CUSTOMER_BK
LEFT JOIN churn                                          ch ON ch.CUSTOMER_BK = c.CUSTOMER_BK;
