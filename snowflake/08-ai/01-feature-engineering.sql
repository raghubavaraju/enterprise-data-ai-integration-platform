-- =============================================================================
-- 08-01  AI.CUSTOMER_FEATURES - point-in-time feature store      [portable]
-- =============================================================================
-- Why a feature table at all, rather than reading CUSTOMER_360 directly?
--
--   * Point-in-time correctness.  A score must be explainable against the
--     features as they were on the scoring date.  CUSTOMER_360 is overwritten
--     on every load; this table is append-only by FEATURE_DATE.
--   * Training/serving parity.  The same table feeds both, so a feature cannot
--     be computed one way for training and another way at serving time - the
--     single most common cause of a model that works in the notebook and fails
--     in production.
--   * Versioning.  FEATURE_SET_VERSION lets a model pin the feature contract it
--     was fitted against, so changing a definition does not silently change
--     every historical score.
--
-- Trend ratios compare the last 90 days against the preceding 275 days on a
-- per-day basis.  A ratio below 1 means the customer is slowing down; this is a
-- far stronger churn signal than absolute volume, which mostly measures how big
-- the customer is instead of whether they are leaving.
-- =============================================================================

DELETE FROM ACME_EDP.AI.CUSTOMER_FEATURES WHERE FEATURE_DATE = CURRENT_DATE;

INSERT INTO ACME_EDP.AI.CUSTOMER_FEATURES
WITH windows AS (
    SELECT
        CUSTOMER_BK,
        SUM(CASE WHEN ORDER_DATE >= CURRENT_DATE - 90 THEN 1 ELSE 0 END)   AS N_90,
        SUM(CASE WHEN ORDER_DATE <  CURRENT_DATE - 90
                  AND ORDER_DATE >= CURRENT_DATE - 365 THEN 1 ELSE 0 END)  AS N_PRIOR,
        SUM(CASE WHEN ORDER_DATE >= CURRENT_DATE - 90
                  AND IS_REVENUE_RECOGNISED THEN NET_AMOUNT ELSE 0 END)    AS R_90,
        SUM(CASE WHEN ORDER_DATE <  CURRENT_DATE - 90
                  AND ORDER_DATE >= CURRENT_DATE - 365
                  AND IS_REVENUE_RECOGNISED THEN NET_AMOUNT ELSE 0 END)    AS R_PRIOR
    FROM ACME_EDP.CORE.SALES_ORDER
    WHERE CUSTOMER_BK IS NOT NULL
    GROUP BY CUSTOMER_BK
)
SELECT
    c.CUSTOMER_BK,
    CURRENT_DATE                                                    AS FEATURE_DATE,
    COALESCE(o.DAYS_SINCE_LAST_ORDER, 9999)                         AS F_RECENCY_DAYS,
    COALESCE(o.ORDERS_LAST_365D, 0)                                 AS F_FREQUENCY_365D,
    COALESCE(o.REVENUE_LAST_365D, 0)                                AS F_MONETARY_365D,
    COALESCE(o.AVG_ORDER_VALUE, 0)                                  AS F_AVG_ORDER_VALUE,
    DATEDIFF(day, CAST(c.SOURCE_CREATED_AT AS DATE), CURRENT_DATE)  AS F_TENURE_DAYS,
    -- per-day rate in the last 90 days vs per-day rate in the prior 275 days
    ROUND(COALESCE((w.N_90 / 90.0) / NULLIF(w.N_PRIOR / 275.0, 0), 0), 4)
                                                                    AS F_ORDER_TREND_RATIO,
    ROUND(COALESCE((w.R_90 / 90.0) / NULLIF(w.R_PRIOR / 275.0, 0), 0), 4)
                                                                    AS F_REVENUE_TREND_RATIO,
    COALESCE(s.CASES_LAST_90D, 0)                                   AS F_CASES_90D,
    COALESCE(s.OPEN_CASES, 0)                                       AS F_OPEN_CASES,
    COALESCE(s.AVG_CSAT, 3.5)                                       AS F_AVG_CSAT,
    COALESCE(s.TOTAL_REOPENS, 0)                                    AS F_REOPEN_COUNT,
    COALESCE(s.SLA_BREACHES, 0)                                     AS F_SLA_BREACHES,
    COALESCE(l.TIER_RANK, 0)                                        AS F_LOYALTY_TIER_RANK,
    COALESCE(DATEDIFF(day, l.LAST_ACTIVITY_AT, CURRENT_DATE), 9999)  AS F_LOYALTY_INACTIVE_DAYS,
    COALESCE(e.ENGAGEMENT_SCORE, 0)                                 AS F_ENGAGEMENT_SCORE,
    COALESCE(e.NEGATIVE_SIGNALS_90D, 0)                             AS F_NEGATIVE_SIGNALS_90D,
    COALESCE(o.RETURN_RATE, 0)                                      AS F_RETURN_RATE,
    'v1.2.0'                                                        AS FEATURE_SET_VERSION,
    NULL                                                            AS _BATCH_ID,
    CURRENT_TIMESTAMP                                               AS _LOADED_AT
FROM ACME_EDP.CORE.CUSTOMER c
LEFT JOIN ACME_EDP.ANALYTICS.CUSTOMER_ORDER_SUMMARY      o ON o.CUSTOMER_BK = c.CUSTOMER_BK
LEFT JOIN ACME_EDP.ANALYTICS.CUSTOMER_SUPPORT_SUMMARY    s ON s.CUSTOMER_BK = c.CUSTOMER_BK
LEFT JOIN ACME_EDP.ANALYTICS.CUSTOMER_ENGAGEMENT_SUMMARY e ON e.CUSTOMER_BK = c.CUSTOMER_BK
LEFT JOIN ACME_EDP.CORE.LOYALTY_ACCOUNT                  l ON l.CUSTOMER_BK = c.CUSTOMER_BK
LEFT JOIN windows                                        w ON w.CUSTOMER_BK = c.CUSTOMER_BK
WHERE c.IS_CURRENT = TRUE;
