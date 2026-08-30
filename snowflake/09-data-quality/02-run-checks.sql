-- =============================================================================
-- 09-02  Execute the rule catalogue      [portable]
-- =============================================================================
-- Each rule's SQL returns a single failing-row count.  In Snowflake this is
-- driven by GOVERNANCE.SP_RUN_DATA_QUALITY (04-procedures) using EXECUTE
-- IMMEDIATE over the catalogue; DuckDB has no stored-procedure equivalent, so
-- the local runner (local_warehouse/dq_runner.py) reads the same rows from the
-- same table and executes the same SQL strings.  One rule definition, two
-- executors - which is the idea of storing rules as data.
--
-- This file contains the *denominator* query used by both executors and a
-- convenience view for reviewing today's results.
-- =============================================================================

CREATE OR REPLACE VIEW ACME_EDP.GOVERNANCE.V_DQ_ROWCOUNTS AS
SELECT 'RAW_CRM_CUSTOMER'      AS TARGET_TABLE, COUNT(*) AS ROWS_EVALUATED FROM ACME_EDP.RAW.RAW_CRM_CUSTOMER
UNION ALL SELECT 'RAW_OMS_ORDER',            COUNT(*) FROM ACME_EDP.RAW.RAW_OMS_ORDER
UNION ALL SELECT 'STG_CUSTOMER',             COUNT(*) FROM ACME_EDP.STAGING.STG_CUSTOMER
UNION ALL SELECT 'STG_SALES_ORDER',          COUNT(*) FROM ACME_EDP.STAGING.STG_SALES_ORDER
UNION ALL SELECT 'STG_SALES_ORDER_ITEM',     COUNT(*) FROM ACME_EDP.STAGING.STG_SALES_ORDER_ITEM
UNION ALL SELECT 'STG_SUPPORT_CASE',         COUNT(*) FROM ACME_EDP.STAGING.STG_SUPPORT_CASE
UNION ALL SELECT 'STG_LOYALTY_ACCOUNT',      COUNT(*) FROM ACME_EDP.STAGING.STG_LOYALTY_ACCOUNT
UNION ALL SELECT 'SALES_ORDER',              COUNT(*) FROM ACME_EDP.CORE.SALES_ORDER
UNION ALL SELECT 'CUSTOMER',                 COUNT(*) FROM ACME_EDP.CORE.CUSTOMER
UNION ALL SELECT 'CUSTOMER_360',             COUNT(*) FROM ACME_EDP.ANALYTICS.CUSTOMER_360
UNION ALL SELECT 'CUSTOMER_CHURN_SCORE',     COUNT(*) FROM ACME_EDP.AI.CUSTOMER_CHURN_SCORE;

-- Latest result per rule, with the steward-facing verdict.
CREATE OR REPLACE VIEW ACME_EDP.GOVERNANCE.V_DQ_LATEST AS
SELECT r.RULE_ID, r.RULE_NAME, r.DIMENSION, r.SEVERITY, r.TARGET_TABLE, r.THRESHOLD_PCT,
       x.ROWS_EVALUATED, x.ROWS_FAILED, x.FAIL_PCT, x.STATUS, x.EXECUTED_AT,
       x.SAMPLE_FAILING_KEYS
FROM ACME_EDP.GOVERNANCE.DQ_RULE r
LEFT JOIN ACME_EDP.GOVERNANCE.DQ_RESULT x
       ON x.RULE_ID = r.RULE_ID
      AND x.EXECUTED_AT = (SELECT MAX(EXECUTED_AT) FROM ACME_EDP.GOVERNANCE.DQ_RESULT
                            WHERE RULE_ID = r.RULE_ID)
WHERE r.IS_ACTIVE = TRUE;
