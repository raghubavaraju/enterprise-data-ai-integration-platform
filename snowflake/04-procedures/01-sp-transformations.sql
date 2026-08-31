-- =============================================================================
-- 04-01  Transformation procedures      [Snowflake only]
-- =============================================================================
-- Thin wrappers around the portable transformation scripts, so the task DAG has
-- something to CALL and so each step logs its own row counts and duration to
-- GOVERNANCE.PIPELINE_RUN_LOG.
--
-- The logic itself stays in 06-transformations/ and 07-customer-360/ rather than
-- being copied in here. A procedure that contains the transformation is a
-- procedure the local warehouse cannot execute, and the whole point of keeping
-- the SQL portable is that it is the SQL that gets tested.
--
-- Every procedure returns a status string and writes a run-log row on both the
-- success and the failure path. A pipeline step that fails silently is worse
-- than one that fails loudly, because the next step consumes its output anyway.
-- =============================================================================

USE DATABASE ACME_EDP;
USE SCHEMA CORE;

CREATE OR REPLACE PROCEDURE CORE.SP_LOAD_STAGING()
RETURNS VARCHAR
LANGUAGE SQL
EXECUTE AS OWNER
AS
$$
DECLARE
    run_id      VARCHAR DEFAULT UUID_STRING();
    started_at  TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP();
    rows_loaded INTEGER DEFAULT 0;
BEGIN
    EXECUTE IMMEDIATE FROM @ACME_EDP.CORE.SCRIPTS/06-transformations/01-raw-to-staging-customer.sql;
    EXECUTE IMMEDIATE FROM @ACME_EDP.CORE.SCRIPTS/06-transformations/02-raw-to-staging-orders.sql;
    EXECUTE IMMEDIATE FROM @ACME_EDP.CORE.SCRIPTS/06-transformations/03-raw-to-staging-service-loyalty.sql;

    SELECT COUNT(*) INTO :rows_loaded FROM ACME_EDP.STAGING.STG_CUSTOMER;

    INSERT INTO ACME_EDP.GOVERNANCE.PIPELINE_RUN_LOG
        (RUN_ID, PIPELINE_NAME, LAYER, LOAD_TYPE, STARTED_AT, ENDED_AT,
         DURATION_SECONDS, ROWS_INSERTED, STATUS)
    SELECT :run_id, 'raw-to-staging', 'STAGING', 'FULL', :started_at, CURRENT_TIMESTAMP(),
           DATEDIFF(second, :started_at, CURRENT_TIMESTAMP()), :rows_loaded, 'SUCCESS';

    RETURN 'SUCCESS: ' || rows_loaded || ' customer rows in STAGING';
EXCEPTION
    WHEN OTHER THEN
        INSERT INTO ACME_EDP.GOVERNANCE.PIPELINE_RUN_LOG
            (RUN_ID, PIPELINE_NAME, LAYER, STARTED_AT, ENDED_AT, STATUS, ERROR_MESSAGE)
        SELECT :run_id, 'raw-to-staging', 'STAGING', :started_at, CURRENT_TIMESTAMP(),
               'FAILED', :sqlerrm;
        RAISE;
END;
$$;

CREATE OR REPLACE PROCEDURE CORE.SP_LOAD_CORE_SCD2()
RETURNS VARCHAR
LANGUAGE SQL
EXECUTE AS OWNER
AS
$$
DECLARE
    run_id     VARCHAR DEFAULT UUID_STRING();
    started_at TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP();
    versions   INTEGER DEFAULT 0;
BEGIN
    -- The incremental MERGE path, which also asserts the three SCD2 invariants
    -- and aborts instead of committing a broken dimension.
    EXECUTE IMMEDIATE FROM @ACME_EDP.CORE.SCRIPTS/05-pipelines/03-incremental-scd2-merge.sql;

    SELECT COUNT(*) INTO :versions
      FROM ACME_EDP.CORE.CUSTOMER WHERE _LOADED_AT >= :started_at;

    INSERT INTO ACME_EDP.GOVERNANCE.PIPELINE_RUN_LOG
        (RUN_ID, PIPELINE_NAME, LAYER, LOAD_TYPE, STARTED_AT, ENDED_AT,
         DURATION_SECONDS, ROWS_INSERTED, STATUS)
    SELECT :run_id, 'staging-to-core-scd2', 'CORE', 'INCREMENTAL', :started_at,
           CURRENT_TIMESTAMP(), DATEDIFF(second, :started_at, CURRENT_TIMESTAMP()),
           :versions, 'SUCCESS';

    RETURN 'SUCCESS: ' || versions || ' customer versions written';
EXCEPTION
    WHEN OTHER THEN
        INSERT INTO ACME_EDP.GOVERNANCE.PIPELINE_RUN_LOG
            (RUN_ID, PIPELINE_NAME, LAYER, STARTED_AT, ENDED_AT, STATUS, ERROR_MESSAGE)
        SELECT :run_id, 'staging-to-core-scd2', 'CORE', :started_at, CURRENT_TIMESTAMP(),
               'FAILED', :sqlerrm;
        RAISE;
END;
$$;

CREATE OR REPLACE PROCEDURE ANALYTICS.SP_BUILD_AGGREGATES()
RETURNS VARCHAR LANGUAGE SQL EXECUTE AS OWNER AS
$$
BEGIN
    EXECUTE IMMEDIATE FROM @ACME_EDP.CORE.SCRIPTS/07-customer-360/01-order-summary.sql;
    EXECUTE IMMEDIATE FROM @ACME_EDP.CORE.SCRIPTS/07-customer-360/02-support-and-engagement-summary.sql;
    RETURN 'SUCCESS';
END;
$$;

CREATE OR REPLACE PROCEDURE AI.SP_BUILD_FEATURES()
RETURNS VARCHAR LANGUAGE SQL EXECUTE AS OWNER AS
$$
BEGIN
    EXECUTE IMMEDIATE FROM @ACME_EDP.CORE.SCRIPTS/08-ai/01-feature-engineering.sql;
    RETURN 'SUCCESS';
END;
$$;

CREATE OR REPLACE PROCEDURE AI.SP_SCORE_CHURN()
RETURNS VARCHAR LANGUAGE SQL EXECUTE AS OWNER AS
$$
BEGIN
    EXECUTE IMMEDIATE FROM @ACME_EDP.CORE.SCRIPTS/08-ai/02-churn-scoring.sql;
    RETURN 'SUCCESS';
END;
$$;

CREATE OR REPLACE PROCEDURE ANALYTICS.SP_BUILD_CUSTOMER_360()
RETURNS VARCHAR LANGUAGE SQL EXECUTE AS OWNER AS
$$
DECLARE
    covered INTEGER DEFAULT 0;
    missing INTEGER DEFAULT 0;
BEGIN
    EXECUTE IMMEDIATE FROM @ACME_EDP.CORE.SCRIPTS/07-customer-360/03-customer-360-build.sql;

    -- DQ-X-001 asserted inline. A CUSTOMER_360 missing customers is the defect
    -- that silently deletes a cohort from every downstream report, and the
    -- cohort it deletes is usually the one that stopped transacting.
    SELECT COUNT(*) INTO :missing
      FROM ACME_EDP.CORE.CUSTOMER c
     WHERE c.IS_CURRENT = TRUE
       AND NOT EXISTS (SELECT 1 FROM ACME_EDP.ANALYTICS.CUSTOMER_360 x
                        WHERE x.CUSTOMER_BK = c.CUSTOMER_BK);
    IF (missing > 0) THEN
        RETURN 'FAILED: ' || missing || ' current customers are absent from CUSTOMER_360';
    END IF;

    SELECT COUNT(*) INTO :covered FROM ACME_EDP.ANALYTICS.CUSTOMER_360;
    RETURN 'SUCCESS: ' || covered || ' customers';
END;
$$;
