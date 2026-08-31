-- =============================================================================
-- 00-01  Warehouse, database and cost guardrails
-- =============================================================================
-- Separate warehouses per workload class.  This is a cost-control decision as
-- much as a performance one: the integration warehouse must stay small and
-- auto-suspend aggressively because Mule calls it in short bursts, while the
-- transformation warehouse is allowed to be larger for a few minutes a day.
-- Mixing them means an interactive API call pays for a batch-sized warehouse.
-- =============================================================================

USE ROLE SYSADMIN;

CREATE WAREHOUSE IF NOT EXISTS ACME_INTEGRATION_WH
    WAREHOUSE_SIZE = 'XSMALL'
    AUTO_SUSPEND = 60                 -- seconds; API traffic is bursty
    AUTO_RESUME = TRUE
    INITIALLY_SUSPENDED = TRUE
    MIN_CLUSTER_COUNT = 1
    MAX_CLUSTER_COUNT = 3             -- multi-cluster: queueing hurts API latency
    SCALING_POLICY = 'STANDARD'
    STATEMENT_TIMEOUT_IN_SECONDS = 30 -- an API-facing query must never run long
    COMMENT = 'Serves synchronous MuleSoft System API queries. Keep it small.';

CREATE WAREHOUSE IF NOT EXISTS ACME_TRANSFORM_WH
    WAREHOUSE_SIZE = 'SMALL'
    AUTO_SUSPEND = 120
    AUTO_RESUME = TRUE
    INITIALLY_SUSPENDED = TRUE
    STATEMENT_TIMEOUT_IN_SECONDS = 3600
    COMMENT = 'Batch RAW->STAGING->CORE->ANALYTICS transformations.';

CREATE WAREHOUSE IF NOT EXISTS ACME_AI_WH
    WAREHOUSE_SIZE = 'SMALL'
    AUTO_SUSPEND = 60
    AUTO_RESUME = TRUE
    INITIALLY_SUSPENDED = TRUE
    STATEMENT_TIMEOUT_IN_SECONDS = 300
    COMMENT = 'Cortex inference and embedding generation. Isolated so that AI '
              'spend is attributable and can be capped independently.';

-- Cost guardrail.  Generative workloads are the easiest way to produce a
-- surprise invoice, so the AI warehouse gets its own monitor with a hard stop.
USE ROLE ACCOUNTADMIN;

CREATE RESOURCE MONITOR IF NOT EXISTS ACME_AI_MONITOR
    WITH CREDIT_QUOTA = 50
    FREQUENCY = MONTHLY
    START_TIMESTAMP = IMMEDIATELY
    TRIGGERS
        ON 60 PERCENT DO NOTIFY
        ON 85 PERCENT DO NOTIFY
        ON 100 PERCENT DO SUSPEND
        ON 110 PERCENT DO SUSPEND_IMMEDIATE;

ALTER WAREHOUSE ACME_AI_WH SET RESOURCE_MONITOR = ACME_AI_MONITOR;

CREATE RESOURCE MONITOR IF NOT EXISTS ACME_PLATFORM_MONITOR
    WITH CREDIT_QUOTA = 400
    FREQUENCY = MONTHLY
    START_TIMESTAMP = IMMEDIATELY
    TRIGGERS
        ON 75 PERCENT DO NOTIFY
        ON 95 PERCENT DO NOTIFY;

USE ROLE SYSADMIN;

CREATE DATABASE IF NOT EXISTS ACME_EDP
    DATA_RETENTION_TIME_IN_DAYS = 7   -- Time Travel; see docs/resilience-and-dr.md
    COMMENT = 'Acme Retail Enterprise Data Platform (POC).';

-- Non-production clones are zero-copy and therefore effectively free to create.
-- This is the mechanism behind the "refresh dev from prod in minutes" claim in
-- docs/deployment.md.
-- CREATE DATABASE ACME_EDP_DEV CLONE ACME_EDP;
