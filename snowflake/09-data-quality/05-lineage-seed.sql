-- =============================================================================
-- 09-05  Declared lineage seed      [portable]
-- =============================================================================
-- Declared (intended) lineage, including the two edges that leave the warehouse
-- and enter MuleSoft.  Most lineage tools stop at the database boundary, which
-- is where a customer-facing platform gets interesting: the question
-- "where does this number on the agent's screen come from?" spans both.
--
-- Snowflake's ACCESS_HISTORY gives *observed* lineage.  Comparing the two is the
-- control: an observed edge with no declared counterpart is undocumented
-- coupling, and a declared edge never observed is dead code.
-- =============================================================================

DELETE FROM ACME_EDP.GOVERNANCE.LINEAGE_EDGE;

INSERT INTO ACME_EDP.GOVERNANCE.LINEAGE_EDGE
 (EDGE_ID, SOURCE_OBJECT, TARGET_OBJECT, TRANSFORMATION, TRANSFORM_SCRIPT, DATA_DOMAIN,
  IS_PII_PROPAGATING, _UPDATED_AT)
VALUES
  ('LIN-001', 'RAW.RAW_CRM_CUSTOMER', 'STAGING.STG_CUSTOMER', 'type, cleanse, validate, dedupe (exact + fuzzy)', '06-transformations/01-raw-to-staging-customer.sql', 'CUSTOMER', TRUE, CURRENT_TIMESTAMP),
  ('LIN-002', 'STAGING.STG_CUSTOMER', 'CORE.CUSTOMER', 'SCD Type 2 load on tracked-attribute hash', '06-transformations/04-staging-to-core-scd2.sql', 'CUSTOMER', TRUE, CURRENT_TIMESTAMP),
  ('LIN-003', 'RAW.RAW_OMS_ORDER', 'STAGING.STG_SALES_ORDER', 'type, validate, dedupe', '06-transformations/02-raw-to-staging-orders.sql', 'ORDER', FALSE, CURRENT_TIMESTAMP),
  ('LIN-004', 'STAGING.STG_SALES_ORDER', 'CORE.SALES_ORDER', 'conform + point-in-time customer key', '06-transformations/04-staging-to-core-scd2.sql', 'ORDER', FALSE, CURRENT_TIMESTAMP),
  ('LIN-005', 'STAGING.STG_SALES_ORDER_ITEM', 'CORE.SALES_ORDER_ITEM', 'conform, drop orphan lines', '06-transformations/04-staging-to-core-scd2.sql', 'ORDER', FALSE, CURRENT_TIMESTAMP),
  ('LIN-006', 'RAW.RAW_SUP_CASE', 'STAGING.STG_SUPPORT_CASE', 'type, chronology validation, resolution hours', '06-transformations/03-raw-to-staging-service-loyalty.sql', 'SERVICE', TRUE, CURRENT_TIMESTAMP),
  ('LIN-007', 'STAGING.STG_SUPPORT_CASE', 'CORE.SUPPORT_CASE', 'conform + SLA breach derivation', '06-transformations/04-staging-to-core-scd2.sql', 'SERVICE', TRUE, CURRENT_TIMESTAMP),
  ('LIN-008', 'RAW.RAW_LOY_ACCOUNT', 'STAGING.STG_LOYALTY_ACCOUNT', 'type, vocabulary and consistency checks', '06-transformations/03-raw-to-staging-service-loyalty.sql', 'LOYALTY', FALSE, CURRENT_TIMESTAMP),
  ('LIN-009', 'STAGING.STG_LOYALTY_ACCOUNT', 'CORE.LOYALTY_ACCOUNT', 'conform + tier rank', '06-transformations/04-staging-to-core-scd2.sql', 'LOYALTY', FALSE, CURRENT_TIMESTAMP),
  ('LIN-010', 'CORE.SALES_ORDER', 'ANALYTICS.CUSTOMER_ORDER_SUMMARY', 'aggregate: RFM, windows, channel, return rate', '07-customer-360/01-order-summary.sql', 'ORDER', FALSE, CURRENT_TIMESTAMP),
  ('LIN-011', 'CORE.SUPPORT_CASE', 'ANALYTICS.CUSTOMER_SUPPORT_SUMMARY', 'aggregate: volume, CSAT, SLA, resolution', '07-customer-360/02-support-and-engagement-summary.sql', 'SERVICE', FALSE, CURRENT_TIMESTAMP),
  ('LIN-012', 'CORE.CUSTOMER_INTERACTION', 'ANALYTICS.CUSTOMER_ENGAGEMENT_SUMMARY', 'aggregate + engagement score', '07-customer-360/02-support-and-engagement-summary.sql', 'CUSTOMER', FALSE, CURRENT_TIMESTAMP),
  ('LIN-013', 'ANALYTICS.CUSTOMER_ORDER_SUMMARY', 'ANALYTICS.CUSTOMER_360', 'join into unified view', '07-customer-360/03-customer-360-build.sql', 'CUSTOMER', FALSE, CURRENT_TIMESTAMP),
  ('LIN-014', 'ANALYTICS.CUSTOMER_SUPPORT_SUMMARY', 'ANALYTICS.CUSTOMER_360', 'join into unified view', '07-customer-360/03-customer-360-build.sql', 'CUSTOMER', FALSE, CURRENT_TIMESTAMP),
  ('LIN-015', 'ANALYTICS.CUSTOMER_ENGAGEMENT_SUMMARY', 'ANALYTICS.CUSTOMER_360', 'join into unified view', '07-customer-360/03-customer-360-build.sql', 'CUSTOMER', FALSE, CURRENT_TIMESTAMP),
  ('LIN-016', 'CORE.CUSTOMER', 'ANALYTICS.CUSTOMER_360', 'current version only', '07-customer-360/03-customer-360-build.sql', 'CUSTOMER', TRUE, CURRENT_TIMESTAMP),
  ('LIN-017', 'ANALYTICS.CUSTOMER_ORDER_SUMMARY', 'AI.CUSTOMER_FEATURES', 'point-in-time feature extraction', '08-ai/01-feature-engineering.sql', 'CUSTOMER', FALSE, CURRENT_TIMESTAMP),
  ('LIN-018', 'AI.CUSTOMER_FEATURES', 'AI.CUSTOMER_CHURN_SCORE', 'weighted rule scoring + driver attribution', '08-ai/02-churn-scoring.sql', 'CUSTOMER', FALSE, CURRENT_TIMESTAMP),
  ('LIN-019', 'AI.CUSTOMER_CHURN_SCORE', 'ANALYTICS.CUSTOMER_360', 'predicted CLV input', '07-customer-360/03-customer-360-build.sql', 'CUSTOMER', FALSE, CURRENT_TIMESTAMP),
  ('LIN-020', 'ANALYTICS.CUSTOMER_360', 'AI.V_CUSTOMER_AI_CONTEXT', 'projection: PII removed by construction', '03-views/02-consumption-views.sql', 'AI', FALSE, CURRENT_TIMESTAMP),
  ('LIN-021', 'AI.V_CUSTOMER_AI_CONTEXT', 'AI.AI_CUSTOMER_INSIGHTS', 'grounded generation', 'services/ai_service', 'AI', FALSE, CURRENT_TIMESTAMP),
  ('LIN-022', 'RAW.RAW_SUP_KNOWLEDGE_ARTICLE', 'AI.KB_DOCUMENT', 'corpus registration', 'services/ai_service/rag.py', 'AI', FALSE, CURRENT_TIMESTAMP),
  ('LIN-023', 'AI.KB_DOCUMENT', 'AI.KB_CHUNK', 'chunk + embed', 'services/ai_service/rag.py', 'AI', FALSE, CURRENT_TIMESTAMP),
  ('LIN-024', 'ANALYTICS.V_CUSTOMER_360_API', 'mule:customer-360-process-api', 'Snowflake System API query', 'mule/system-api/snowflake-data-api', 'CUSTOMER', TRUE, CURRENT_TIMESTAMP),
  ('LIN-025', 'mule:customer-360-process-api', 'mule:customer-experience-api', 'aggregate + shape + mask', 'mule/experience-api', 'CUSTOMER', TRUE, CURRENT_TIMESTAMP);
