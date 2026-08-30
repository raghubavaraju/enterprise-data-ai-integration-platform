-- =============================================================================
-- 02-GOVERNANCE  Operational metadata
-- =============================================================================

CREATE TABLE IF NOT EXISTS ACME_EDP.GOVERNANCE.DATA_DICTIONARY (
    SCHEMA_NAME              VARCHAR(64),
    TABLE_NAME               VARCHAR(128),
    COLUMN_NAME              VARCHAR(128),
    DATA_TYPE                VARCHAR(64),
    BUSINESS_DEFINITION      VARCHAR(2000),
    DATA_DOMAIN              VARCHAR(64),
    CLASSIFICATION           VARCHAR(32),   -- PUBLIC | INTERNAL | CONFIDENTIAL | RESTRICTED
    IS_PII                   BOOLEAN,
    PII_CATEGORY             VARCHAR(64),   -- DIRECT_IDENTIFIER | QUASI_IDENTIFIER | NONE
    DATA_OWNER               VARCHAR(128),
    DATA_STEWARD             VARCHAR(128),
    SOURCE_SYSTEM            VARCHAR(64),
    RETENTION_MONTHS         NUMBER(6,0),
    MASKING_POLICY           VARCHAR(128),
    _UPDATED_AT              TIMESTAMP_NTZ
);

CREATE TABLE IF NOT EXISTS ACME_EDP.GOVERNANCE.DQ_RULE (
    RULE_ID                  VARCHAR(64) NOT NULL,
    RULE_NAME                VARCHAR(200),
    DIMENSION                VARCHAR(32),   -- COMPLETENESS | VALIDITY | UNIQUENESS |
                                            -- CONSISTENCY | ACCURACY | TIMELINESS
    TARGET_SCHEMA            VARCHAR(64),
    TARGET_TABLE             VARCHAR(128),
    TARGET_COLUMN            VARCHAR(128),
    SEVERITY                 VARCHAR(16),   -- BLOCKING | WARNING | INFO
    THRESHOLD_PCT            NUMBER(5,2),
    RULE_SQL                 VARCHAR(16777216),
    OWNER                    VARCHAR(128),
    IS_ACTIVE                BOOLEAN,
    CONSTRAINT PK_DQ_RULE PRIMARY KEY (RULE_ID)
);

CREATE TABLE IF NOT EXISTS ACME_EDP.GOVERNANCE.DQ_RESULT (
    RESULT_ID                VARCHAR(64) NOT NULL,
    RULE_ID                  VARCHAR(64),
    RUN_ID                   VARCHAR(64),
    EXECUTED_AT              TIMESTAMP_NTZ,
    ROWS_EVALUATED           NUMBER(18,0),
    ROWS_FAILED              NUMBER(18,0),
    FAIL_PCT                 NUMBER(9,4),
    STATUS                   VARCHAR(16),   -- PASS | WARN | FAIL
    SAMPLE_FAILING_KEYS      VARCHAR(4000),
    _CORRELATION_ID          VARCHAR(64),
    CONSTRAINT PK_DQ_RESULT PRIMARY KEY (RESULT_ID)
);

CREATE TABLE IF NOT EXISTS ACME_EDP.GOVERNANCE.PIPELINE_RUN_LOG (
    RUN_ID                   VARCHAR(64) NOT NULL,
    PIPELINE_NAME            VARCHAR(200),
    LAYER                    VARCHAR(32),
    LOAD_TYPE                VARCHAR(16),   -- FULL | INCREMENTAL | CDC
    STARTED_AT               TIMESTAMP_NTZ,
    ENDED_AT                 TIMESTAMP_NTZ,
    DURATION_SECONDS         NUMBER(12,2),
    ROWS_READ                NUMBER(18,0),
    ROWS_INSERTED            NUMBER(18,0),
    ROWS_UPDATED             NUMBER(18,0),
    ROWS_REJECTED            NUMBER(18,0),
    STATUS                   VARCHAR(16),   -- SUCCESS | PARTIAL | FAILED
    ERROR_MESSAGE            VARCHAR(4000),
    HIGH_WATER_MARK          VARCHAR(64),
    _BATCH_ID                VARCHAR(64),
    _CORRELATION_ID          VARCHAR(64),
    CONSTRAINT PK_PIPELINE_RUN_LOG PRIMARY KEY (RUN_ID)
);

-- Declared lineage.  Snowflake ACCESS_HISTORY gives observed lineage; this table
-- gives *intended* lineage.  The gap between the two is the interesting signal:
-- an edge in ACCESS_HISTORY with no matching row here is undocumented coupling.
CREATE TABLE IF NOT EXISTS ACME_EDP.GOVERNANCE.LINEAGE_EDGE (
    EDGE_ID                  VARCHAR(64) NOT NULL,
    SOURCE_OBJECT            VARCHAR(300),
    TARGET_OBJECT            VARCHAR(300),
    TRANSFORMATION           VARCHAR(200),
    TRANSFORM_SCRIPT         VARCHAR(300),
    DATA_DOMAIN              VARCHAR(64),
    IS_PII_PROPAGATING       BOOLEAN,
    _UPDATED_AT              TIMESTAMP_NTZ,
    CONSTRAINT PK_LINEAGE_EDGE PRIMARY KEY (EDGE_ID)
);

CREATE TABLE IF NOT EXISTS ACME_EDP.GOVERNANCE.INGESTION_WATERMARK (
    SOURCE_SYSTEM            VARCHAR(64) NOT NULL,
    SOURCE_ENTITY            VARCHAR(128) NOT NULL,
    WATERMARK_COLUMN         VARCHAR(128),
    LAST_VALUE               VARCHAR(64),
    LAST_RUN_ID              VARCHAR(64),
    LAST_SUCCESS_AT          TIMESTAMP_NTZ,
    CONSTRAINT PK_INGESTION_WATERMARK PRIMARY KEY (SOURCE_SYSTEM, SOURCE_ENTITY)
) COMMENT = 'Incremental ingestion high-water marks. Updated only after a load '
            'commits, so a failed run re-reads and not skips.';
