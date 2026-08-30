-- =============================================================================
-- 09-04  Data dictionary seed      [portable]
-- =============================================================================
-- A representative slice of the enterprise data dictionary, held as data so it
-- can be joined to INFORMATION_SCHEMA and diffed in CI.  The full generated
-- dictionary is docs/data-dictionary.md.
--
-- Every column that carries PII names the masking policy that governs it, and
-- every derived column states its definition in business language.  A column
-- whose definition cannot be written in one sentence usually means the model is
-- wrong, not that the sentence is hard.
-- =============================================================================

DELETE FROM ACME_EDP.GOVERNANCE.DATA_DICTIONARY;

INSERT INTO ACME_EDP.GOVERNANCE.DATA_DICTIONARY
 (SCHEMA_NAME, TABLE_NAME, COLUMN_NAME, DATA_TYPE, BUSINESS_DEFINITION, DATA_DOMAIN,
  CLASSIFICATION, IS_PII, PII_CATEGORY, DATA_OWNER, DATA_STEWARD, SOURCE_SYSTEM,
  RETENTION_MONTHS, MASKING_POLICY, _UPDATED_AT)
VALUES
  ('CORE', 'CUSTOMER', 'CUSTOMER_BK', 'VARCHAR', 'CRM-issued business key for the customer. Stable for the life of the record.', 'CUSTOMER', 'INTERNAL', FALSE, 'NONE', 'VP Customer Experience', 'Customer Data Steward', 'CRM', 84, NULL, CURRENT_TIMESTAMP),
  ('CORE', 'CUSTOMER', 'FIRST_NAME', 'VARCHAR', 'Customer given name as captured in the CRM.', 'CUSTOMER', 'CONFIDENTIAL', TRUE, 'DIRECT_IDENTIFIER', 'VP Customer Experience', 'Customer Data Steward', 'CRM', 84, 'MP_NAME', CURRENT_TIMESTAMP),
  ('CORE', 'CUSTOMER', 'LAST_NAME', 'VARCHAR', 'Customer family name as captured in the CRM.', 'CUSTOMER', 'CONFIDENTIAL', TRUE, 'DIRECT_IDENTIFIER', 'VP Customer Experience', 'Customer Data Steward', 'CRM', 84, 'MP_NAME', CURRENT_TIMESTAMP),
  ('CORE', 'CUSTOMER', 'EMAIL', 'VARCHAR', 'Primary e-mail address. Also the strongest identity-resolution key.', 'CUSTOMER', 'RESTRICTED', TRUE, 'DIRECT_IDENTIFIER', 'VP Customer Experience', 'Customer Data Steward', 'CRM', 84, 'MP_EMAIL', CURRENT_TIMESTAMP),
  ('CORE', 'CUSTOMER', 'PHONE', 'VARCHAR', 'Primary telephone number, digits and leading + only.', 'CUSTOMER', 'RESTRICTED', TRUE, 'DIRECT_IDENTIFIER', 'VP Customer Experience', 'Customer Data Steward', 'CRM', 84, 'MP_PHONE', CURRENT_TIMESTAMP),
  ('CORE', 'CUSTOMER', 'BIRTH_DATE', 'DATE', 'Date of birth. Quasi-identifier: generalised to year for most consumers.', 'CUSTOMER', 'RESTRICTED', TRUE, 'QUASI_IDENTIFIER', 'VP Customer Experience', 'Customer Data Steward', 'CRM', 84, 'MP_DATE_GENERALISE', CURRENT_TIMESTAMP),
  ('CORE', 'CUSTOMER', 'MARKETING_OPT_IN', 'BOOLEAN', 'Marketing consent flag. History is retained because consent state at a point in time is auditable.', 'CUSTOMER', 'CONFIDENTIAL', FALSE, 'NONE', 'Chief Privacy Officer', 'Customer Data Steward', 'CRM', 84, NULL, CURRENT_TIMESTAMP),
  ('CORE', 'CUSTOMER', 'VALID_FROM', 'TIMESTAMP', 'Start of this version''s validity window; sourced from the CRM update timestamp, not from load time.', 'CUSTOMER', 'INTERNAL', FALSE, 'NONE', 'Data Platform Owner', 'Data Platform Steward', 'DERIVED', 84, NULL, CURRENT_TIMESTAMP),
  ('CORE', 'CUSTOMER', 'IS_CURRENT', 'BOOLEAN', 'TRUE for exactly one version per customer. Enforced by DQ-X-002.', 'CUSTOMER', 'INTERNAL', FALSE, 'NONE', 'Data Platform Owner', 'Data Platform Steward', 'DERIVED', 84, NULL, CURRENT_TIMESTAMP),
  ('CORE', 'SALES_ORDER', 'ORDER_BK', 'VARCHAR', 'OMS order number.', 'ORDER', 'INTERNAL', FALSE, 'NONE', 'VP Commerce', 'Order Data Steward', 'OMS', 84, NULL, CURRENT_TIMESTAMP),
  ('CORE', 'SALES_ORDER', 'NET_AMOUNT', 'DECIMAL', 'Order amount less discount, excluding shipping. The revenue figure used everywhere downstream.', 'ORDER', 'INTERNAL', FALSE, 'NONE', 'VP Commerce', 'Order Data Steward', 'OMS', 84, NULL, CURRENT_TIMESTAMP),
  ('CORE', 'SALES_ORDER', 'IS_REVENUE_RECOGNISED', 'BOOLEAN', 'TRUE for COMPLETED and SHIPPED orders only. Single definition of recognised revenue.', 'ORDER', 'INTERNAL', FALSE, 'NONE', 'VP Commerce', 'Order Data Steward', 'DERIVED', 84, NULL, CURRENT_TIMESTAMP),
  ('CORE', 'SALES_ORDER', 'CUSTOMER_SK', 'VARCHAR', 'Customer version current at the order date. Enables point-in-time attribution.', 'ORDER', 'INTERNAL', FALSE, 'NONE', 'Data Platform Owner', 'Data Platform Steward', 'DERIVED', 84, NULL, CURRENT_TIMESTAMP),
  ('CORE', 'SUPPORT_CASE', 'DESCRIPTION', 'VARCHAR', 'Free-text customer complaint. May contain incidental PII; redacted before any AI call.', 'SERVICE', 'RESTRICTED', TRUE, 'DIRECT_IDENTIFIER', 'VP Customer Service', 'Service Data Steward', 'SUPPORT', 36, 'MP_FREE_TEXT', CURRENT_TIMESTAMP),
  ('CORE', 'SUPPORT_CASE', 'CSAT_SCORE', 'DECIMAL', 'Post-resolution satisfaction score, 1-5.', 'SERVICE', 'INTERNAL', FALSE, 'NONE', 'VP Customer Service', 'Service Data Steward', 'SUPPORT', 36, NULL, CURRENT_TIMESTAMP),
  ('CORE', 'SUPPORT_CASE', 'IS_SLA_BREACHED', 'BOOLEAN', 'Resolution time exceeded the priority SLA from KB-010.', 'SERVICE', 'INTERNAL', FALSE, 'NONE', 'VP Customer Service', 'Service Data Steward', 'DERIVED', 36, NULL, CURRENT_TIMESTAMP),
  ('CORE', 'LOYALTY_ACCOUNT', 'TIER', 'VARCHAR', 'BRONZE/SILVER/GOLD/PLATINUM, recalculated monthly on trailing 12-month spend.', 'LOYALTY', 'INTERNAL', FALSE, 'NONE', 'VP Loyalty', 'Loyalty Data Steward', 'LOYALTY', 84, NULL, CURRENT_TIMESTAMP),
  ('ANALYTICS', 'CUSTOMER_360', 'ENGAGEMENT_SCORE', 'DECIMAL', '0-100 weighted engagement index. Deterministic; weights documented in docs/data-architecture.md.', 'CUSTOMER', 'INTERNAL', FALSE, 'NONE', 'VP Customer Experience', 'Data Platform Steward', 'DERIVED', 24, NULL, CURRENT_TIMESTAMP),
  ('ANALYTICS', 'CUSTOMER_360', 'CUSTOMER_LIFETIME_VALUE', 'DECIMAL', 'Realised net revenue to date on recognised orders. NOT a prediction.', 'CUSTOMER', 'INTERNAL', FALSE, 'NONE', 'VP Commerce', 'Data Platform Steward', 'DERIVED', 24, NULL, CURRENT_TIMESTAMP),
  ('ANALYTICS', 'CUSTOMER_360', 'PREDICTED_CLV_12M', 'DECIMAL', 'Projected 12-month value: AOV x annualised frequency x (1 - churn probability). Always labelled as predicted.', 'CUSTOMER', 'INTERNAL', FALSE, 'NONE', 'VP Commerce', 'Data Platform Steward', 'DERIVED', 24, NULL, CURRENT_TIMESTAMP),
  ('ANALYTICS', 'CUSTOMER_360', 'DATA_COMPLETENESS_SCORE', 'DECIMAL', 'Percentage of eight profile attributes populated. Lets a consumer distinguish absent data from an unavailable source.', 'CUSTOMER', 'INTERNAL', FALSE, 'NONE', 'Data Platform Owner', 'Data Platform Steward', 'DERIVED', 24, NULL, CURRENT_TIMESTAMP),
  ('AI', 'CUSTOMER_FEATURES', 'F_ORDER_TREND_RATIO', 'DECIMAL', 'Order rate in the last 90 days divided by the rate in the prior 275 days. Below 1 means slowing.', 'CUSTOMER', 'INTERNAL', FALSE, 'NONE', 'AI Platform Owner', 'AI Platform Steward', 'DERIVED', 24, NULL, CURRENT_TIMESTAMP),
  ('AI', 'CUSTOMER_CHURN_SCORE', 'CHURN_PROBABILITY', 'DECIMAL', 'Baseline rule-weighted churn score in [0,1]. Not a calibrated probability from a fitted model.', 'CUSTOMER', 'INTERNAL', FALSE, 'NONE', 'AI Platform Owner', 'AI Platform Steward', 'DERIVED', 24, NULL, CURRENT_TIMESTAMP),
  ('AI', 'CUSTOMER_CHURN_SCORE', 'TOP_DRIVER_1', 'VARCHAR', 'Largest contributing factor to the score. Stored so the explanation is reproducible.', 'CUSTOMER', 'INTERNAL', FALSE, 'NONE', 'AI Platform Owner', 'AI Platform Steward', 'DERIVED', 24, NULL, CURRENT_TIMESTAMP),
  ('AI', 'AI_CUSTOMER_INSIGHTS', 'GENERATED_TEXT', 'VARCHAR', 'Model-generated narrative. Never a system of record; never re-used as model input without human approval.', 'AI', 'CONFIDENTIAL', FALSE, 'NONE', 'AI Platform Owner', 'AI Platform Steward', 'DERIVED', 24, NULL, CURRENT_TIMESTAMP),
  ('AI', 'AI_CUSTOMER_INSIGHTS', 'GROUNDING_SNAPSHOT', 'JSON', 'The exact facts supplied to the model for this generation. The evidence for any later dispute.', 'AI', 'CONFIDENTIAL', FALSE, 'NONE', 'AI Platform Owner', 'AI Platform Steward', 'DERIVED', 24, NULL, CURRENT_TIMESTAMP),
  ('AI', 'AI_REQUEST_AUDIT', 'REQUESTED_BY_CLIENT_ID', 'VARCHAR', 'OAuth client that triggered the generation. Required for cost attribution and abuse investigation.', 'AI', 'INTERNAL', FALSE, 'NONE', 'AI Platform Owner', 'AI Platform Steward', 'DERIVED', 24, NULL, CURRENT_TIMESTAMP);
