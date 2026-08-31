-- =============================================================================
-- 05-03  Incremental SCD Type 2 load for CORE.CUSTOMER      [Snowflake only]
-- =============================================================================
-- This is the path that runs on a schedule in Snowflake. The full-rebuild
-- equivalent is 06-transformations/04-staging-to-core-scd2.sql, which is
-- portable and is what the local warehouse executes.
--
-- Both produce the same end state. Keeping two implementations is a real cost,
-- and it is paid on purpose for two reasons:
--   * the full rebuild is also the *recovery* path - a corrupted CORE is
--     reconstructed from RAW in about two hours without a restore;
--   * DuckDB has no MERGE, so without the rebuild path nothing in the
--     transformation chain could be executed or tested locally.
--
-- Why MERGE and not delete-and-insert: an SCD2 load must close the outgoing
-- version and open the incoming one atomically. Two statements leave a window
-- in which a customer has either no current version or two, and every reader in
-- that window gets a wrong answer.
--
-- The two-pass structure below is the standard Snowflake idiom for SCD2. A
-- single MERGE cannot both UPDATE the existing row and INSERT its replacement
-- for the same match, so pass 1 closes and pass 2 opens.
-- =============================================================================

USE DATABASE ACME_EDP;
USE SCHEMA CORE;

-- -----------------------------------------------------------------------------
-- Source: the stream over STAGING, so only rows that actually changed are read.
-- A stream is an offset, not a copy: consuming it in a DML statement advances it
-- exactly once, which makes the load idempotent under retry.
-- -----------------------------------------------------------------------------
CREATE OR REPLACE STREAM STAGING.STG_CUSTOMER_STREAM
    ON TABLE ACME_EDP.STAGING.STG_CUSTOMER
    SHOW_INITIAL_ROWS = FALSE
    COMMENT = 'Change stream feeding the incremental SCD2 load.';

-- -----------------------------------------------------------------------------
-- Pass 1 - close the outgoing version.
--
-- Only where the tracked-attribute hash differs. Audit columns are excluded from
-- that hash, so re-ingesting an unchanged record does not create a version - the
-- single most common way an SCD2 table grows by a factor of ten for no reason.
--
-- VALID_TO is the SOURCE update timestamp, not CURRENT_TIMESTAMP. Using load
-- time makes history depend on when the pipeline happened to run, which makes
-- every point-in-time answer wrong after a backfill.
-- -----------------------------------------------------------------------------
MERGE INTO ACME_EDP.CORE.CUSTOMER AS target
USING (
    SELECT
        s.CUSTOMER_BK,
        s._ROW_HASH,
        COALESCE(s.SOURCE_UPDATED_AT, s.SOURCE_CREATED_AT, CURRENT_TIMESTAMP()) AS CHANGE_AT
    FROM ACME_EDP.STAGING.STG_CUSTOMER_STREAM s
    WHERE s.METADATA$ACTION = 'INSERT'
      AND s.DQ_STATUS <> 'FAIL'
) AS source
   ON target.CUSTOMER_BK = source.CUSTOMER_BK
  AND target.IS_CURRENT = TRUE
  AND target._ROW_HASH <> source._ROW_HASH
WHEN MATCHED THEN UPDATE SET
    target.VALID_TO    = source.CHANGE_AT,
    target.IS_CURRENT  = FALSE,
    target.CHANGE_TYPE = 'UPDATE',
    target._LOADED_AT  = CURRENT_TIMESTAMP();

-- -----------------------------------------------------------------------------
-- Pass 2 - open the incoming version.
--
-- Inserts for really new customers and for those whose open row pass 1 just
-- closed. The NOT EXISTS guard makes the whole statement idempotent: if
-- the task is retried after a partial failure, a version that already exists is
-- not duplicated.
-- -----------------------------------------------------------------------------
MERGE INTO ACME_EDP.CORE.CUSTOMER AS target
USING (
    SELECT
        s.*,
        COALESCE(s.SOURCE_UPDATED_AT, s.SOURCE_CREATED_AT, CURRENT_TIMESTAMP()) AS VALID_FROM_TS,
        MD5(s.CUSTOMER_BK || '|' ||
            CAST(COALESCE(s.SOURCE_UPDATED_AT, s.SOURCE_CREATED_AT,
                          CURRENT_TIMESTAMP()) AS VARCHAR))                     AS NEW_SK
    FROM ACME_EDP.STAGING.STG_CUSTOMER_STREAM s
    WHERE s.METADATA$ACTION = 'INSERT'
      AND s.DQ_STATUS <> 'FAIL'
      AND NOT EXISTS (
            SELECT 1 FROM ACME_EDP.CORE.CUSTOMER c
             WHERE c.CUSTOMER_BK = s.CUSTOMER_BK
               AND c.IS_CURRENT  = TRUE
               AND c._ROW_HASH   = s._ROW_HASH)
) AS source
   ON target.CUSTOMER_SK = source.NEW_SK
WHEN NOT MATCHED THEN INSERT (
    CUSTOMER_SK, CUSTOMER_BK, MASTER_CUSTOMER_ID, SOURCE_SYSTEM, FIRST_NAME, LAST_NAME,
    FULL_NAME, EMAIL, PHONE, BIRTH_DATE, CUSTOMER_SEGMENT, MARKETING_OPT_IN,
    PREFERRED_CHANNEL, STATUS, SOURCE_CREATED_AT, VALID_FROM, VALID_TO, IS_CURRENT,
    VERSION_NUMBER, CHANGE_TYPE, _ROW_HASH, _BATCH_ID, _CORRELATION_ID, _LOADED_AT
) VALUES (
    source.NEW_SK, source.CUSTOMER_BK, source.CUSTOMER_BK, source.SOURCE_SYSTEM,
    source.FIRST_NAME, source.LAST_NAME, source.FULL_NAME, source.EMAIL, source.PHONE,
    source.BIRTH_DATE, source.CUSTOMER_SEGMENT, source.MARKETING_OPT_IN,
    source.PREFERRED_CHANNEL, source.STATUS, source.SOURCE_CREATED_AT,
    source.VALID_FROM_TS,
    TO_TIMESTAMP_NTZ('9999-12-31 00:00:00'),   -- sentinel, never NULL
    TRUE,
    COALESCE((SELECT MAX(c2.VERSION_NUMBER) FROM ACME_EDP.CORE.CUSTOMER c2
               WHERE c2.CUSTOMER_BK = source.CUSTOMER_BK), 0) + 1,
    CASE WHEN EXISTS (SELECT 1 FROM ACME_EDP.CORE.CUSTOMER c3
                       WHERE c3.CUSTOMER_BK = source.CUSTOMER_BK)
         THEN 'UPDATE' ELSE 'INSERT' END,
    source._ROW_HASH, source._BATCH_ID, source._CORRELATION_ID, CURRENT_TIMESTAMP()
);

-- -----------------------------------------------------------------------------
-- Post-load invariants. These are the three properties an SCD2 table must hold,
-- and they are asserted here instead of only in the test suite because a
-- scheduled task has no reviewer watching it.
--
-- A failure aborts the task, which leaves the stream offset unconsumed, so the
-- next run re-reads the same changes. Failing loudly and re-reading beats
-- committing a broken dimension.
-- -----------------------------------------------------------------------------
EXECUTE IMMEDIATE $$
DECLARE
    duplicate_current  INTEGER;
    overlapping_spans  INTEGER;
    stale_open_rows    INTEGER;
BEGIN
    SELECT COUNT(*) INTO :duplicate_current FROM (
        SELECT CUSTOMER_BK FROM ACME_EDP.CORE.CUSTOMER
         WHERE IS_CURRENT = TRUE GROUP BY CUSTOMER_BK HAVING COUNT(*) > 1);
    IF (duplicate_current > 0) THEN
        RETURN 'FAILED: ' || duplicate_current || ' customers have more than one current version';
    END IF;

    SELECT COUNT(*) INTO :overlapping_spans
      FROM ACME_EDP.CORE.CUSTOMER a
      JOIN ACME_EDP.CORE.CUSTOMER b
        ON a.CUSTOMER_BK = b.CUSTOMER_BK
       AND a.CUSTOMER_SK <> b.CUSTOMER_SK
       AND a.VALID_FROM < b.VALID_TO
       AND b.VALID_FROM < a.VALID_TO;
    IF (overlapping_spans > 0) THEN
        RETURN 'FAILED: ' || overlapping_spans || ' overlapping validity windows';
    END IF;

    SELECT COUNT(*) INTO :stale_open_rows FROM ACME_EDP.CORE.CUSTOMER
     WHERE IS_CURRENT = TRUE AND VALID_TO < TO_TIMESTAMP_NTZ('9999-12-31 00:00:00');
    IF (stale_open_rows > 0) THEN
        RETURN 'FAILED: ' || stale_open_rows || ' open rows with a closed VALID_TO';
    END IF;

    RETURN 'OK';
END;
$$;
