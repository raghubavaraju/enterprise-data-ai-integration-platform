-- =============================================================================
-- 05-04  Task DAG - scheduled orchestration      [Snowflake only]
-- =============================================================================
-- The same run order the local build uses (local_warehouse/build.py), expressed
-- as a Snowflake task DAG.
--
-- The order is not alphabetical because there is a genuine dependency cycle to
-- break: CUSTOMER_360 wants the churn probability for predicted CLV; churn
-- scoring wants the feature store; the feature store wants the ANALYTICS
-- aggregates. So the aggregates run first, then features, then scores, and
-- CUSTOMER_360 last.
--
-- Tasks use ACME_TRANSFORM_WH, not the integration warehouse. Running batch on
-- the warehouse that serves API reads is how an interactive endpoint acquires a
-- nightly latency spike.
-- =============================================================================

USE DATABASE ACME_EDP;
USE SCHEMA CORE;

-- Root: 03:00 UTC daily. Everything else hangs off this.
CREATE OR REPLACE TASK T_ROOT_DAILY_LOAD
    WAREHOUSE = ACME_TRANSFORM_WH
    SCHEDULE = 'USING CRON 0 3 * * * UTC'
    SUSPEND_TASK_AFTER_NUM_FAILURES = 3
    COMMENT = 'Root of the nightly transformation DAG.'
AS
    INSERT INTO ACME_EDP.GOVERNANCE.PIPELINE_RUN_LOG
        (RUN_ID, PIPELINE_NAME, LAYER, LOAD_TYPE, STARTED_AT, STATUS, _BATCH_ID)
    SELECT UUID_STRING(), 'daily-load', 'ALL', 'INCREMENTAL', CURRENT_TIMESTAMP(),
           'RUNNING', TO_VARCHAR(CURRENT_DATE, 'YYYYMMDD');

CREATE OR REPLACE TASK T_RAW_TO_STAGING
    WAREHOUSE = ACME_TRANSFORM_WH
    AFTER T_ROOT_DAILY_LOAD
AS
    CALL ACME_EDP.CORE.SP_LOAD_STAGING();

CREATE OR REPLACE TASK T_STAGING_TO_CORE
    WAREHOUSE = ACME_TRANSFORM_WH
    AFTER T_RAW_TO_STAGING
    -- The stream gate: no changes, no run, no credits. Without it the DAG burns
    -- a warehouse every night whether or not anything happened.
    WHEN SYSTEM$STREAM_HAS_DATA('ACME_EDP.STAGING.STG_CUSTOMER_STREAM')
AS
    CALL ACME_EDP.CORE.SP_LOAD_CORE_SCD2();

CREATE OR REPLACE TASK T_ANALYTICS_AGGREGATES
    WAREHOUSE = ACME_TRANSFORM_WH
    AFTER T_STAGING_TO_CORE
AS
    CALL ACME_EDP.ANALYTICS.SP_BUILD_AGGREGATES();

CREATE OR REPLACE TASK T_AI_FEATURES
    WAREHOUSE = ACME_TRANSFORM_WH
    AFTER T_ANALYTICS_AGGREGATES
AS
    CALL ACME_EDP.AI.SP_BUILD_FEATURES();

CREATE OR REPLACE TASK T_AI_CHURN_SCORING
    WAREHOUSE = ACME_TRANSFORM_WH
    AFTER T_AI_FEATURES
AS
    CALL ACME_EDP.AI.SP_SCORE_CHURN();

CREATE OR REPLACE TASK T_CUSTOMER_360
    WAREHOUSE = ACME_TRANSFORM_WH
    AFTER T_AI_CHURN_SCORING
AS
    CALL ACME_EDP.ANALYTICS.SP_BUILD_CUSTOMER_360();

-- Data quality runs LAST and does not gate the load. Deliberate: the platform
-- reports defects, it does not hide the data. A BLOCKING failure raises an
-- alert and the affected rows are already quarantined by the transformation.
CREATE OR REPLACE TASK T_DATA_QUALITY
    WAREHOUSE = ACME_TRANSFORM_WH
    AFTER T_CUSTOMER_360
AS
    CALL ACME_EDP.GOVERNANCE.SP_RUN_DATA_QUALITY();

-- Embeddings refresh only when an article's content hash changed. Re-embedding
-- an unchanged corpus every night is pure Cortex spend for no benefit.
CREATE OR REPLACE TASK T_RAG_REFRESH
    WAREHOUSE = ACME_AI_WH
    AFTER T_DATA_QUALITY
AS
    CALL ACME_EDP.AI.SP_REFRESH_KB_EMBEDDINGS();

-- Tasks are created suspended. Resume children before the root, or the root
-- fires with no downstream attached and the DAG silently does nothing.
ALTER TASK T_RAG_REFRESH RESUME;
ALTER TASK T_DATA_QUALITY RESUME;
ALTER TASK T_CUSTOMER_360 RESUME;
ALTER TASK T_AI_CHURN_SCORING RESUME;
ALTER TASK T_AI_FEATURES RESUME;
ALTER TASK T_ANALYTICS_AGGREGATES RESUME;
ALTER TASK T_STAGING_TO_CORE RESUME;
ALTER TASK T_RAW_TO_STAGING RESUME;
ALTER TASK T_ROOT_DAILY_LOAD RESUME;

CREATE OR REPLACE VIEW ACME_EDP.GOVERNANCE.V_TASK_HEALTH AS
SELECT NAME, STATE, SCHEDULED_TIME, COMPLETED_TIME,
       DATEDIFF(second, SCHEDULED_TIME, COMPLETED_TIME) AS DURATION_SECONDS,
       ERROR_MESSAGE
FROM TABLE(INFORMATION_SCHEMA.TASK_HISTORY(
        SCHEDULED_TIME_RANGE_START => DATEADD(day, -7, CURRENT_TIMESTAMP())))
ORDER BY SCHEDULED_TIME DESC;
