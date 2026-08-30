-- =============================================================================
-- 04-02  Data quality runner      [Snowflake only]
-- =============================================================================
-- Reads GOVERNANCE.DQ_RULE and executes each rule's stored SQL with
-- EXECUTE IMMEDIATE, then writes GOVERNANCE.DQ_RESULT.
--
-- This is one of *two* executors over the same rule rows. The other is
-- local_warehouse/dq_runner.py, which does exactly the same thing without a
-- Snowflake account. One rule definition, two executors - which is the point of
-- storing rules as data rather than writing them as code: a steward adds a rule
-- with an INSERT and both executors pick it up with no deployment.
--
-- Severity semantics, implemented here:
--   BLOCKING  fails above threshold; the offending rows were already quarantined
--             by the transformation, so this raises an alert instead of gating
--   WARNING   flags above threshold; appears on the steward's scorecard
--   INFO      measured and trended; never fails
--
-- A rule whose SQL no longer parses is recorded as an ERROR with ROWS_FAILED = -1
-- rather than being skipped. A broken rule that looks like coverage while
-- checking nothing is worse than a missing rule.
-- =============================================================================

USE DATABASE ACME_EDP;
USE SCHEMA GOVERNANCE;

CREATE OR REPLACE PROCEDURE GOVERNANCE.SP_RUN_DATA_QUALITY(CORRELATION_ID VARCHAR DEFAULT NULL)
RETURNS VARCHAR
LANGUAGE SQL
EXECUTE AS OWNER
AS
$$
DECLARE
    run_id       VARCHAR DEFAULT UUID_STRING();
    executed_at  TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP();
    n_pass       INTEGER DEFAULT 0;
    n_warn       INTEGER DEFAULT 0;
    n_fail       INTEGER DEFAULT 0;
    n_error      INTEGER DEFAULT 0;
    failed_rows  INTEGER;
    total_rows   INTEGER;
    fail_pct     FLOAT;
    verdict      VARCHAR;
    rules CURSOR FOR
        SELECT RULE_ID, RULE_NAME, SEVERITY, TARGET_TABLE, THRESHOLD_PCT, RULE_SQL
          FROM ACME_EDP.GOVERNANCE.DQ_RULE
         WHERE IS_ACTIVE = TRUE
         ORDER BY RULE_ID;
BEGIN
    FOR rule IN rules DO
        BEGIN
            -- The rule's own SQL returns a single failing-row count.
            EXECUTE IMMEDIATE :rule.RULE_SQL;
            SELECT $1 INTO :failed_rows FROM TABLE(RESULT_SCAN(LAST_QUERY_ID()));

            SELECT COALESCE(MAX(ROWS_EVALUATED), 0) INTO :total_rows
              FROM ACME_EDP.GOVERNANCE.V_DQ_ROWCOUNTS
             WHERE TARGET_TABLE = :rule.TARGET_TABLE;

            fail_pct := IFF(total_rows = 0,
                            IFF(failed_rows > 0, 100.0, 0.0),
                            failed_rows * 100.0 / total_rows);

            verdict := CASE
                WHEN failed_rows = 0 OR fail_pct <= rule.THRESHOLD_PCT THEN 'PASS'
                WHEN rule.SEVERITY = 'BLOCKING' THEN 'FAIL'
                WHEN rule.SEVERITY = 'WARNING'  THEN 'WARN'
                ELSE 'PASS'          -- INFO rules are measured, never gate
            END;

            n_pass  := n_pass  + IFF(verdict = 'PASS', 1, 0);
            n_warn  := n_warn  + IFF(verdict = 'WARN', 1, 0);
            n_fail  := n_fail  + IFF(verdict = 'FAIL', 1, 0);

            INSERT INTO ACME_EDP.GOVERNANCE.DQ_RESULT
                (RESULT_ID, RULE_ID, RUN_ID, EXECUTED_AT, ROWS_EVALUATED, ROWS_FAILED,
                 FAIL_PCT, STATUS, _CORRELATION_ID)
            SELECT MD5(:run_id || ':' || :rule.RULE_ID), :rule.RULE_ID, :run_id,
                   :executed_at, :total_rows, :failed_rows, :fail_pct, :verdict,
                   :CORRELATION_ID;
        EXCEPTION
            WHEN OTHER THEN
                n_error := n_error + 1;
                INSERT INTO ACME_EDP.GOVERNANCE.DQ_RESULT
                    (RESULT_ID, RULE_ID, RUN_ID, EXECUTED_AT, ROWS_EVALUATED, ROWS_FAILED,
                     FAIL_PCT, STATUS, SAMPLE_FAILING_KEYS, _CORRELATION_ID)
                SELECT MD5(:run_id || ':' || :rule.RULE_ID), :rule.RULE_ID, :run_id,
                       :executed_at, 0, -1, 0.0, 'FAIL',
                       'rule execution error: ' || :sqlerrm, :CORRELATION_ID;
        END;
    END FOR;

    RETURN 'run=' || run_id ||
           ' pass=' || n_pass || ' warn=' || n_warn ||
           ' fail=' || n_fail || ' error=' || n_error;
END;
$$;

-- Alert hook: a BLOCKING failure is a P1. Wired to a Snowflake alert instead of
-- to a dashboard, because a dashboard is only seen by someone already looking.
CREATE OR REPLACE ALERT GOVERNANCE.ALERT_DQ_BLOCKING_FAILURE
    WAREHOUSE = ACME_TRANSFORM_WH
    SCHEDULE = '30 MINUTE'
    IF (EXISTS (
        SELECT 1 FROM ACME_EDP.GOVERNANCE.V_DQ_LATEST
         WHERE STATUS = 'FAIL' AND SEVERITY = 'BLOCKING'
           AND EXECUTED_AT >= DATEADD(hour, -24, CURRENT_TIMESTAMP())))
    THEN CALL SYSTEM$SEND_EMAIL(
        'acme_data_platform_alerts',
        'data-platform-oncall@example.com.com',
        'P1: blocking data quality failure in ACME_EDP',
        'One or more BLOCKING data quality rules failed. See GOVERNANCE.V_DQ_LATEST.');
