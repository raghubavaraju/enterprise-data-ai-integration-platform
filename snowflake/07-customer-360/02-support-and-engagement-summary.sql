-- =============================================================================
-- 07-02  Support and engagement aggregates      [portable]
-- =============================================================================

DELETE FROM ACME_EDP.ANALYTICS.CUSTOMER_SUPPORT_SUMMARY;

INSERT INTO ACME_EDP.ANALYTICS.CUSTOMER_SUPPORT_SUMMARY
WITH top_type AS (
    SELECT CUSTOMER_BK, CASE_TYPE AS TOP_CASE_TYPE
    FROM (
        SELECT CUSTOMER_BK, CASE_TYPE,
               ROW_NUMBER() OVER (PARTITION BY CUSTOMER_BK
                                  ORDER BY COUNT(*) DESC, CASE_TYPE) AS RN
        FROM ACME_EDP.CORE.SUPPORT_CASE
        WHERE CUSTOMER_BK IS NOT NULL
        GROUP BY CUSTOMER_BK, CASE_TYPE
    ) t WHERE RN = 1
)
SELECT
    s.CUSTOMER_BK,
    COUNT(*)                                                              AS TOTAL_CASES,
    SUM(CASE WHEN s.STATUS = 'OPEN' THEN 1 ELSE 0 END)                    AS OPEN_CASES,
    SUM(CASE WHEN s.OPENED_AT >= CAST(CURRENT_DATE - 90  AS TIMESTAMP) THEN 1 ELSE 0 END)
                                                                          AS CASES_LAST_90D,
    SUM(CASE WHEN s.OPENED_AT >= CAST(CURRENT_DATE - 365 AS TIMESTAMP) THEN 1 ELSE 0 END)
                                                                          AS CASES_LAST_365D,
    ROUND(AVG(s.CSAT_SCORE), 2)                                           AS AVG_CSAT,
    MIN(s.CSAT_SCORE)                                                     AS MIN_CSAT,
    ROUND(AVG(s.RESOLUTION_HOURS), 2)                                     AS AVG_RESOLUTION_HOURS,
    SUM(COALESCE(s.REOPEN_COUNT, 0))                                      AS TOTAL_REOPENS,
    SUM(CASE WHEN s.IS_SLA_BREACHED THEN 1 ELSE 0 END)                    AS SLA_BREACHES,
    MAX(t.TOP_CASE_TYPE)                                                  AS TOP_CASE_TYPE,
    CAST(MAX(s.OPENED_AT) AS DATE)                                        AS LAST_CASE_DATE,
    DATEDIFF(day, CAST(MAX(s.OPENED_AT) AS DATE), CURRENT_DATE)           AS DAYS_SINCE_LAST_CASE,
    CURRENT_DATE                                                          AS AS_OF_DATE,
    CURRENT_TIMESTAMP                                                     AS _LOADED_AT
FROM ACME_EDP.CORE.SUPPORT_CASE s
LEFT JOIN top_type t ON t.CUSTOMER_BK = s.CUSTOMER_BK
WHERE s.CUSTOMER_BK IS NOT NULL
GROUP BY s.CUSTOMER_BK;

DELETE FROM ACME_EDP.ANALYTICS.CUSTOMER_ENGAGEMENT_SUMMARY;

-- Driven from CORE.CUSTOMER, not from the interaction table: a customer with no
-- interactions must still get a row (with zeroes), otherwise CUSTOMER_360 loses
-- them on the join and the "no engagement" cohort silently disappears - which is
-- exactly the cohort the churn model cares most about.
--
-- ENGAGEMENT_SCORE is defined here, once.  CUSTOMER_360 and the AI feature store
-- both read it instead of each re-deriving it; two implementations of the same
-- score is how a customer ends up "engaged" on the dashboard and "disengaged" in
-- the model on the same day.
INSERT INTO ACME_EDP.ANALYTICS.CUSTOMER_ENGAGEMENT_SUMMARY
WITH ix AS (
    SELECT
        CUSTOMER_BK,
        SUM(CASE WHEN INTERACTION_TS >= CAST(CURRENT_DATE - 90  AS TIMESTAMP) THEN 1 ELSE 0 END)
            AS INTERACTIONS_LAST_90D,
        SUM(CASE WHEN INTERACTION_TS >= CAST(CURRENT_DATE - 365 AS TIMESTAMP) THEN 1 ELSE 0 END)
            AS INTERACTIONS_LAST_365D,
        SUM(CASE WHEN IS_NEGATIVE_SIGNAL
                      AND INTERACTION_TS >= CAST(CURRENT_DATE - 90 AS TIMESTAMP)
                 THEN 1 ELSE 0 END)                       AS NEGATIVE_SIGNALS_90D,
        CAST(MAX(INTERACTION_TS) AS DATE)                 AS LAST_INTERACTION_DATE,
        COUNT(DISTINCT CHANNEL)                           AS DISTINCT_CHANNELS
    FROM ACME_EDP.CORE.CUSTOMER_INTERACTION
    WHERE CUSTOMER_BK IS NOT NULL
    GROUP BY CUSTOMER_BK
)
SELECT
    c.CUSTOMER_BK,
    COALESCE(ix.INTERACTIONS_LAST_90D, 0),
    COALESCE(ix.INTERACTIONS_LAST_365D, 0),
    COALESCE(ix.NEGATIVE_SIGNALS_90D, 0),
    ix.LAST_INTERACTION_DATE,
    DATEDIFF(day, ix.LAST_INTERACTION_DATE, CURRENT_DATE),
    COALESCE(ix.DISTINCT_CHANNELS, 0),
    -- ------------------------------------------------- ENGAGEMENT_SCORE (0-100)
    -- Weighted, capped, and fully explainable.  The weights are a documented
    -- business assumption (docs/data-architecture.md), not a fitted model:
    --   recency of ordering 30 | frequency 25 | interactions 15
    --   loyalty standing    15 | service health 15 | negative-signal penalty -10
    ROUND(GREATEST(0, LEAST(100,
          30 * GREATEST(0, 1 - COALESCE(o.DAYS_SINCE_LAST_ORDER, 999) / 365.0)
        + 25 * LEAST(1, COALESCE(o.ORDER_FREQUENCY_PER_YEAR, 0) / 12.0)
        + 15 * LEAST(1, COALESCE(ix.INTERACTIONS_LAST_90D, 0) / 10.0)
        + 15 * (COALESCE(l.TIER_RANK, 0) / 4.0)
        + 15 * (COALESCE(s.AVG_CSAT, 3.5) - 1) / 4.0
        - 10 * LEAST(1, COALESCE(ix.NEGATIVE_SIGNALS_90D, 0) / 3.0)
    )), 2)                                                AS ENGAGEMENT_SCORE,
    CURRENT_DATE,
    CURRENT_TIMESTAMP
FROM ACME_EDP.CORE.CUSTOMER c
LEFT JOIN ix                                          ON ix.CUSTOMER_BK = c.CUSTOMER_BK
LEFT JOIN ACME_EDP.ANALYTICS.CUSTOMER_ORDER_SUMMARY   o ON o.CUSTOMER_BK  = c.CUSTOMER_BK
LEFT JOIN ACME_EDP.ANALYTICS.CUSTOMER_SUPPORT_SUMMARY s ON s.CUSTOMER_BK  = c.CUSTOMER_BK
LEFT JOIN ACME_EDP.CORE.LOYALTY_ACCOUNT               l ON l.CUSTOMER_BK  = c.CUSTOMER_BK
WHERE c.IS_CURRENT = TRUE;
