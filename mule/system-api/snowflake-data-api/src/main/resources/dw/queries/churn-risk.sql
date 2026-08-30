-- Statement executed by GET /customers/{customerId}/churn-risk.
--
-- Returns the STORED drivers alongside the score. They are not recomputed here
-- and they are not inferred by a model: the explanation a business user sees
-- months later must be the one that produced the number.
SELECT CUSTOMER_BK AS CUSTOMER_ID, SCORE_DATE, CHURN_PROBABILITY, CHURN_RISK_BAND,
       MODEL_NAME, MODEL_VERSION, SCORING_METHOD, FEATURE_SET_VERSION,
       TOP_DRIVER_1, TOP_DRIVER_1_CONTRIB,
       TOP_DRIVER_2, TOP_DRIVER_2_CONTRIB,
       TOP_DRIVER_3, TOP_DRIVER_3_CONTRIB
FROM ACME_EDP.AI.CUSTOMER_CHURN_SCORE
WHERE CUSTOMER_BK = ?
ORDER BY SCORE_DATE DESC
LIMIT 1
