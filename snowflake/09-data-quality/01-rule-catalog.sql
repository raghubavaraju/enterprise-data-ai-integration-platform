-- =============================================================================
-- 09-01  Data quality rule catalogue      [portable]
-- =============================================================================
-- Rules are *data*, not code.  Storing them in a table instead of hard-coding
-- them in scripts is what lets a data steward add a rule without a deployment,
-- lets the scorecard render itself, and lets severity be tuned per environment.
--
-- Severity semantics:
--   BLOCKING  the row is quarantined and never reaches CORE
--   WARNING   the row loads, is flagged, and appears on the steward's scorecard
--   INFO      measured and trended only
--
-- A rule is only BLOCKING when loading the row would corrupt a number someone
-- makes a decision on.  Over-using BLOCKING is how a data platform becomes
-- famous for rejecting the business's data.
-- =============================================================================

DELETE FROM ACME_EDP.GOVERNANCE.DQ_RULE;

INSERT INTO ACME_EDP.GOVERNANCE.DQ_RULE
 (RULE_ID, RULE_NAME, DIMENSION, TARGET_SCHEMA, TARGET_TABLE, TARGET_COLUMN, SEVERITY,
  THRESHOLD_PCT, RULE_SQL, OWNER, IS_ACTIVE)
VALUES
 ('DQ-C-001','Customer business key must be present','COMPLETENESS','RAW','RAW_CRM_CUSTOMER',
  'CUSTOMER_ID','BLOCKING',0.00,
  'SELECT COUNT(*) FROM ACME_EDP.RAW.RAW_CRM_CUSTOMER WHERE CUSTOMER_ID IS NULL OR TRIM(CUSTOMER_ID) = ''''',
  'Customer Data Domain Owner',TRUE),

 ('DQ-C-002','Customer e-mail must be syntactically valid','VALIDITY','STAGING','STG_CUSTOMER',
  'EMAIL','WARNING',2.00,
  'SELECT COUNT(*) FROM ACME_EDP.STAGING.STG_CUSTOMER WHERE EMAIL_IS_VALID = FALSE',
  'Customer Data Domain Owner',TRUE),

 ('DQ-C-003','Date of birth must be plausible','VALIDITY','STAGING','STG_CUSTOMER',
  'BIRTH_DATE','WARNING',1.00,
  'SELECT COUNT(*) FROM ACME_EDP.STAGING.STG_CUSTOMER WHERE BIRTH_DATE > CURRENT_DATE OR BIRTH_DATE < DATE ''1900-01-01''',
  'Customer Data Domain Owner',TRUE),

 ('DQ-C-004','Customer status must be from the controlled vocabulary','CONSISTENCY','STAGING',
  'STG_CUSTOMER','STATUS','WARNING',0.50,
  'SELECT COUNT(*) FROM ACME_EDP.STAGING.STG_CUSTOMER WHERE STATUS NOT IN (''ACTIVE'',''INACTIVE'',''CLOSED'')',
  'Customer Data Domain Owner',TRUE),

 ('DQ-C-005','No duplicate customers by match key','UNIQUENESS','RAW','RAW_CRM_CUSTOMER',
  'EMAIL','WARNING',1.00,
  'SELECT COUNT(*) FROM (SELECT LOWER(TRIM(EMAIL)) AS E FROM ACME_EDP.RAW.RAW_CRM_CUSTOMER WHERE EMAIL IS NOT NULL GROUP BY 1 HAVING COUNT(DISTINCT CUSTOMER_ID) > 1) d',
  'Customer Data Domain Owner',TRUE),

 ('DQ-O-001','Order business key must be present','COMPLETENESS','RAW','RAW_OMS_ORDER',
  'ORDER_ID','BLOCKING',0.00,
  'SELECT COUNT(*) FROM ACME_EDP.RAW.RAW_OMS_ORDER WHERE ORDER_ID IS NULL',
  'Order Data Domain Owner',TRUE),

 ('DQ-O-002','Order amount must be non-negative','VALIDITY','STAGING','STG_SALES_ORDER',
  'ORDER_AMOUNT','BLOCKING',0.00,
  'SELECT COUNT(*) FROM ACME_EDP.STAGING.STG_SALES_ORDER WHERE ORDER_AMOUNT IS NULL OR ORDER_AMOUNT < 0',
  'Order Data Domain Owner',TRUE),

 ('DQ-O-003','Order date must not be in the future','VALIDITY','STAGING','STG_SALES_ORDER',
  'ORDER_DATE','BLOCKING',0.00,
  'SELECT COUNT(*) FROM ACME_EDP.STAGING.STG_SALES_ORDER WHERE ORDER_DATE IS NULL OR ORDER_DATE > CURRENT_DATE',
  'Order Data Domain Owner',TRUE),

 ('DQ-O-006','Every order must reference a known customer','CONSISTENCY','CORE','SALES_ORDER',
  'CUSTOMER_BK','WARNING',0.00,
  'SELECT COUNT(*) FROM ACME_EDP.CORE.SALES_ORDER o WHERE o.CUSTOMER_BK IS NOT NULL AND NOT EXISTS (SELECT 1 FROM ACME_EDP.CORE.CUSTOMER c WHERE c.CUSTOMER_BK = o.CUSTOMER_BK)',
  'Order Data Domain Owner',TRUE),

 ('DQ-OI-002','Order line amount must equal quantity x unit price','ACCURACY','STAGING',
  'STG_SALES_ORDER_ITEM','LINE_AMOUNT','WARNING',1.00,
  'SELECT COUNT(*) FROM ACME_EDP.STAGING.STG_SALES_ORDER_ITEM WHERE ABS(COALESCE(LINE_AMOUNT,0) - COALESCE(QUANTITY,0) * COALESCE(UNIT_PRICE,0)) > 0.01',
  'Order Data Domain Owner',TRUE),

 ('DQ-OI-003','Every order line must reference a known product','CONSISTENCY','STAGING',
  'STG_SALES_ORDER_ITEM','PRODUCT_BK','WARNING',0.00,
  'SELECT COUNT(*) FROM ACME_EDP.STAGING.STG_SALES_ORDER_ITEM i WHERE i.PRODUCT_BK IS NOT NULL AND NOT EXISTS (SELECT 1 FROM ACME_EDP.STAGING.STG_PRODUCT p WHERE p.PRODUCT_BK = i.PRODUCT_BK)',
  'Product Data Domain Owner',TRUE),

 ('DQ-S-002','Support case cannot be resolved before it was opened','VALIDITY','STAGING',
  'STG_SUPPORT_CASE','RESOLVED_AT','BLOCKING',0.00,
  'SELECT COUNT(*) FROM ACME_EDP.STAGING.STG_SUPPORT_CASE WHERE RESOLVED_AT IS NOT NULL AND OPENED_AT IS NOT NULL AND RESOLVED_AT < OPENED_AT',
  'Service Data Domain Owner',TRUE),

 ('DQ-S-003','CSAT score must be between 1 and 5','VALIDITY','STAGING','STG_SUPPORT_CASE',
  'CSAT_SCORE','WARNING',0.50,
  'SELECT COUNT(*) FROM ACME_EDP.STAGING.STG_SUPPORT_CASE WHERE CSAT_SCORE IS NOT NULL AND (CSAT_SCORE < 1 OR CSAT_SCORE > 5)',
  'Service Data Domain Owner',TRUE),

 ('DQ-L-003','Redeemed points cannot exceed points ever earned','CONSISTENCY','STAGING',
  'STG_LOYALTY_ACCOUNT','POINTS_REDEEMED_LIFETIME','WARNING',1.00,
  'SELECT COUNT(*) FROM ACME_EDP.STAGING.STG_LOYALTY_ACCOUNT WHERE COALESCE(POINTS_REDEEMED_LIFETIME,0) > COALESCE(POINTS_EARNED_LIFETIME,0)',
  'Loyalty Data Domain Owner',TRUE),

 ('DQ-X-001','Customer 360 must cover every current customer','COMPLETENESS','ANALYTICS',
  'CUSTOMER_360','CUSTOMER_BK','BLOCKING',0.00,
  'SELECT COUNT(*) FROM ACME_EDP.CORE.CUSTOMER c WHERE c.IS_CURRENT = TRUE AND NOT EXISTS (SELECT 1 FROM ACME_EDP.ANALYTICS.CUSTOMER_360 x WHERE x.CUSTOMER_BK = c.CUSTOMER_BK)',
  'Data Platform Owner',TRUE),

 ('DQ-X-002','Exactly one current version per customer','UNIQUENESS','CORE','CUSTOMER',
  'IS_CURRENT','BLOCKING',0.00,
  'SELECT COUNT(*) FROM (SELECT CUSTOMER_BK FROM ACME_EDP.CORE.CUSTOMER WHERE IS_CURRENT = TRUE GROUP BY CUSTOMER_BK HAVING COUNT(*) > 1) d',
  'Data Platform Owner',TRUE),

 ('DQ-X-003','SCD2 validity windows must not overlap','CONSISTENCY','CORE','CUSTOMER',
  'VALID_FROM','BLOCKING',0.00,
  'SELECT COUNT(*) FROM ACME_EDP.CORE.CUSTOMER a JOIN ACME_EDP.CORE.CUSTOMER b ON a.CUSTOMER_BK = b.CUSTOMER_BK AND a.CUSTOMER_SK <> b.CUSTOMER_SK AND a.VALID_FROM < b.VALID_TO AND b.VALID_FROM < a.VALID_TO',
  'Data Platform Owner',TRUE),

 ('DQ-X-004','Revenue outliers for review','ACCURACY','ANALYTICS','CUSTOMER_360',
  'TOTAL_NET_REVENUE','INFO',5.00,
  'SELECT COUNT(*) FROM ACME_EDP.ANALYTICS.CUSTOMER_360 WHERE TOTAL_NET_REVENUE > (SELECT AVG(TOTAL_NET_REVENUE) + 3 * STDDEV(TOTAL_NET_REVENUE) FROM ACME_EDP.ANALYTICS.CUSTOMER_360)',
  'Data Platform Owner',TRUE),

 ('DQ-X-005','Churn score must exist for every scored customer','COMPLETENESS','AI',
  'CUSTOMER_CHURN_SCORE','CHURN_PROBABILITY','WARNING',0.00,
  'SELECT COUNT(*) FROM ACME_EDP.AI.CUSTOMER_FEATURES f WHERE f.FEATURE_DATE = CURRENT_DATE AND NOT EXISTS (SELECT 1 FROM ACME_EDP.AI.CUSTOMER_CHURN_SCORE s WHERE s.CUSTOMER_BK = f.CUSTOMER_BK AND s.SCORE_DATE = f.FEATURE_DATE)',
  'AI Platform Owner',TRUE),

 ('DQ-X-006','Churn probability must be a probability','VALIDITY','AI','CUSTOMER_CHURN_SCORE',
  'CHURN_PROBABILITY','BLOCKING',0.00,
  'SELECT COUNT(*) FROM ACME_EDP.AI.CUSTOMER_CHURN_SCORE WHERE CHURN_PROBABILITY < 0 OR CHURN_PROBABILITY > 1',
  'AI Platform Owner',TRUE),

 -- Timeliness is the dimension teams forget, and it is the one that produces
 -- the most damaging kind of wrong answer: a number that is internally
 -- consistent, passes every other check, and describes last week.
 ('DQ-X-007','Customer 360 must be no more than 24 hours old','TIMELINESS','ANALYTICS',
  'CUSTOMER_360','AS_OF_TIMESTAMP','BLOCKING',0.00,
  'SELECT COUNT(*) FROM ACME_EDP.ANALYTICS.CUSTOMER_360 WHERE AS_OF_TIMESTAMP < CURRENT_TIMESTAMP - INTERVAL ''24 hours''',
  'Data Platform Owner',TRUE),

 ('DQ-X-008','Churn scores must be refreshed daily','TIMELINESS','AI','CUSTOMER_CHURN_SCORE',
  'SCORE_DATE','WARNING',0.00,
  'SELECT COUNT(*) FROM ACME_EDP.AI.CUSTOMER_CHURN_SCORE WHERE SCORE_DATE < CURRENT_DATE',
  'AI Platform Owner',TRUE);
