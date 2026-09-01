-- =============================================================================
-- 08-02  AI.CUSTOMER_CHURN_SCORE - transparent baseline scoring      [portable]
-- =============================================================================
-- This is a intentionally *interpretable, rule-weighted* baseline, not a trained
-- classifier.  Reasons, and they are the same reasons a real programme starts
-- here:
--
--   1. There is no labelled churn outcome in this dataset.  Fitting a model
--      against a fabricated label would produce a number that looks credible
--      and means nothing.  A stated heuristic is honest; a fake AUC is not.
--   2. A weighted-rule score is fully explainable, which is a hard requirement
--      when the output drives an agent-visible recommendation and an
--      AI-generated explanation.
--   3. It is a working baseline.  When real labels exist, the ML model must
--      beat this, and SCORING_METHOD/MODEL_VERSION let both run side by side.
--
-- The contract with the AI layer matters more than the arithmetic: the drivers
-- are computed and *stored*, and the LLM explains stored drivers.  It never
-- infers why a customer might churn, because that is where hallucination enters.
--
-- Production path: replace this script with Snowpark ML or an external model
-- registered in Snowflake; AI.CUSTOMER_CHURN_SCORE keeps the same shape and
-- nothing downstream changes.  See docs/ai-architecture.md.
-- =============================================================================

DELETE FROM ACME_EDP.AI.CUSTOMER_CHURN_SCORE WHERE SCORE_DATE = CURRENT_DATE;

INSERT INTO ACME_EDP.AI.CUSTOMER_CHURN_SCORE
WITH contrib AS (
    SELECT
        f.CUSTOMER_BK,
        -- Each term is a bounded contribution in [0, weight].  Weights sum to 1.
        0.30 * LEAST(1.0, f.F_RECENCY_DAYS / 240.0)                        AS C_RECENCY,
        0.20 * GREATEST(0.0, 1.0 - LEAST(1.0, f.F_ORDER_TREND_RATIO))      AS C_TREND,
        0.15 * LEAST(1.0, f.F_CASES_90D / 3.0)                             AS C_SERVICE_LOAD,
        0.10 * GREATEST(0.0, (4.0 - LEAST(5.0, f.F_AVG_CSAT)) / 3.0)       AS C_CSAT,
        0.10 * GREATEST(0.0, 1.0 - f.F_ENGAGEMENT_SCORE / 100.0)           AS C_ENGAGEMENT,
        0.08 * LEAST(1.0, f.F_LOYALTY_INACTIVE_DAYS / 365.0)               AS C_LOYALTY,
        0.07 * LEAST(1.0, f.F_NEGATIVE_SIGNALS_90D / 2.0)                  AS C_NEGATIVE,
        f.FEATURE_SET_VERSION
    FROM ACME_EDP.AI.CUSTOMER_FEATURES f
    WHERE f.FEATURE_DATE = CURRENT_DATE
),
ranked AS (
    SELECT
        c.*,
        ROUND(C_RECENCY + C_TREND + C_SERVICE_LOAD + C_CSAT
              + C_ENGAGEMENT + C_LOYALTY + C_NEGATIVE, 4)                  AS CHURN_PROBABILITY
    FROM contrib c
),
-- One unpivot, ranked once, reused three times.  Repeating the union per driver
-- slot would triple the scan for no benefit.
driver_ranked AS (
    SELECT CUSTOMER_BK, DRIVER_NAME, CONTRIB,
           ROW_NUMBER() OVER (PARTITION BY CUSTOMER_BK
                              ORDER BY CONTRIB DESC, DRIVER_NAME) AS DRIVER_RANK
    FROM (
        SELECT CUSTOMER_BK, 'PURCHASE_RECENCY'       AS DRIVER_NAME, C_RECENCY      AS CONTRIB FROM ranked
        UNION ALL SELECT CUSTOMER_BK, 'DECLINING_ORDER_TREND',       C_TREND        FROM ranked
        UNION ALL SELECT CUSTOMER_BK, 'SUPPORT_CASE_VOLUME',         C_SERVICE_LOAD FROM ranked
        UNION ALL SELECT CUSTOMER_BK, 'LOW_SATISFACTION',            C_CSAT         FROM ranked
        UNION ALL SELECT CUSTOMER_BK, 'LOW_ENGAGEMENT',              C_ENGAGEMENT   FROM ranked
        UNION ALL SELECT CUSTOMER_BK, 'LOYALTY_INACTIVITY',          C_LOYALTY      FROM ranked
        UNION ALL SELECT CUSTOMER_BK, 'NEGATIVE_SIGNALS',            C_NEGATIVE     FROM ranked
    ) u
)
SELECT
    r.CUSTOMER_BK,
    CURRENT_DATE                                                            AS SCORE_DATE,
    LEAST(0.9900, GREATEST(0.0100, r.CHURN_PROBABILITY))                    AS CHURN_PROBABILITY,
    CASE
        WHEN r.CHURN_PROBABILITY >= 0.70 THEN 'CRITICAL'
        WHEN r.CHURN_PROBABILITY >= 0.50 THEN 'HIGH'
        WHEN r.CHURN_PROBABILITY >= 0.30 THEN 'MEDIUM'
        ELSE 'LOW'
    END                                                                     AS CHURN_RISK_BAND,
    'acme-churn-baseline'                                                   AS MODEL_NAME,
    'v1.2.0'                                                                AS MODEL_VERSION,
    'RULE_BASED'                                                            AS SCORING_METHOD,
    d1.DRIVER_NAME                                                          AS TOP_DRIVER_1,
    ROUND(d1.CONTRIB, 4)                                                    AS TOP_DRIVER_1_CONTRIB,
    d2.DRIVER_NAME                                                          AS TOP_DRIVER_2,
    ROUND(d2.CONTRIB, 4)                                                    AS TOP_DRIVER_2_CONTRIB,
    d3.DRIVER_NAME                                                          AS TOP_DRIVER_3,
    ROUND(d3.CONTRIB, 4)                                                    AS TOP_DRIVER_3_CONTRIB,
    r.FEATURE_SET_VERSION,
    NULL                                                                    AS _BATCH_ID,
    NULL                                                                    AS _CORRELATION_ID,
    CURRENT_TIMESTAMP                                                       AS _LOADED_AT
FROM ranked r
LEFT JOIN driver_ranked d1 ON d1.CUSTOMER_BK = r.CUSTOMER_BK AND d1.DRIVER_RANK = 1
LEFT JOIN driver_ranked d2 ON d2.CUSTOMER_BK = r.CUSTOMER_BK AND d2.DRIVER_RANK = 2
LEFT JOIN driver_ranked d3 ON d3.CUSTOMER_BK = r.CUSTOMER_BK AND d3.DRIVER_RANK = 3;
