-- =============================================================================
-- 01-01  Schemas - one per architectural layer
-- =============================================================================
-- The layer boundary is also the *contract* boundary:
--   RAW        immutable landing.  Never queried by a consumer. Never modified.
--   STAGING    typed, cleansed, deduplicated.  Disposable and rebuildable.
--   CORE       enterprise entities, conformed, historised.  The system of record
--              for analytics.  Only CORE has slowly changing dimensions.
--   ANALYTICS  consumption-shaped aggregates, incl. CUSTOMER_360.
--   AI         features, scores, generated content and AI audit.  Separated
--              because its governance rules differ (see ADR-004).
--   GOVERNANCE operational metadata: data dictionary, DQ rules and results,
--              pipeline run log, lineage edges.
-- =============================================================================

USE DATABASE ACME_EDP;

CREATE SCHEMA IF NOT EXISTS RAW
    DATA_RETENTION_TIME_IN_DAYS = 1
    COMMENT = 'Immutable landing zone. Source-shaped. No business logic.';

CREATE SCHEMA IF NOT EXISTS STAGING
    DATA_RETENTION_TIME_IN_DAYS = 1
    COMMENT = 'Typed, cleansed, deduplicated. Rebuildable from RAW at any time.';

CREATE SCHEMA IF NOT EXISTS CORE
    DATA_RETENTION_TIME_IN_DAYS = 7
    COMMENT = 'Conformed enterprise entities with history. System of record for analytics.';

CREATE SCHEMA IF NOT EXISTS ANALYTICS
    DATA_RETENTION_TIME_IN_DAYS = 7
    COMMENT = 'Consumption-shaped models, including CUSTOMER_360.';

CREATE SCHEMA IF NOT EXISTS AI
    DATA_RETENTION_TIME_IN_DAYS = 7
    COMMENT = 'Feature store, model scores, generated insights and AI audit trail.';

CREATE SCHEMA IF NOT EXISTS GOVERNANCE
    DATA_RETENTION_TIME_IN_DAYS = 30
    COMMENT = 'Data dictionary, data quality rules and results, lineage, run log.';
