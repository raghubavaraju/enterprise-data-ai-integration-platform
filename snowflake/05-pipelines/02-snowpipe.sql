-- =============================================================================
-- 05-02  Snowpipe - continuous ingestion      [Snowflake only]
-- =============================================================================
-- Snowpipe rather than a scheduled COPY for the feeds that need freshness:
-- it is serverless, so it does not hold a warehouse awake between files, and it
-- is triggered by the arrival of a file rather than by a clock. A scheduled COPY
-- either runs too often (and pays for an idle warehouse) or too rarely (and adds
-- latency that has nothing to do with the data).
--
-- Every pipe stamps the audit columns at load time. _SRC_FILE and _INGESTED_AT
-- are what make a row in RAW traceable back to the exact file it came from,
-- which is the first question asked when a number looks wrong.
--
-- AUTO_INGEST = TRUE requires an event notification from the object store to the
-- pipe's SQS queue; the ARN is read from SYSTEM$PIPE_STATUS after creation and
-- configured on the bucket.
-- =============================================================================

USE DATABASE ACME_EDP;
USE SCHEMA RAW;

CREATE PIPE IF NOT EXISTS PIPE_CRM_CUSTOMER
    AUTO_INGEST = TRUE
    COMMENT = 'Continuous ingestion of CRM customer extracts.'
AS
COPY INTO ACME_EDP.RAW.RAW_CRM_CUSTOMER (
    CUSTOMER_ID, SOURCE_SYSTEM, FIRST_NAME, LAST_NAME, EMAIL, PHONE, BIRTH_DATE,
    CUSTOMER_SEGMENT, MARKETING_OPT_IN, PREFERRED_CHANNEL, STATUS, CREATED_AT,
    UPDATED_AT, SRC_PAYLOAD, _SRC_SYSTEM, _SRC_FILE, _INGESTED_AT, _BATCH_ID,
    _CORRELATION_ID, _ROW_HASH
)
FROM (
    SELECT
        $1:customerId::VARCHAR,
        COALESCE($1:sourceSystem::VARCHAR, 'CRM'),
        $1:firstName::VARCHAR,
        $1:lastName::VARCHAR,
        $1:email::VARCHAR,
        $1:phone::VARCHAR,
        $1:birthDate::VARCHAR,
        $1:customerSegment::VARCHAR,
        $1:marketingOptIn::VARCHAR,
        $1:preferredChannel::VARCHAR,
        $1:status::VARCHAR,
        $1:createdAt::VARCHAR,
        $1:updatedAt::VARCHAR,
        $1,                                     -- untyped payload: schema evolution
        'CRM',
        METADATA$FILENAME,
        METADATA$START_SCAN_TIME,
        SPLIT_PART(METADATA$FILENAME, '/', -1), -- the file name is the batch id
        NULL,                                   -- set by the Mule path, not by Snowpipe
        MD5(TO_JSON($1))
    FROM @STG_CRM
)
FILE_FORMAT = (FORMAT_NAME = FF_JSON)
ON_ERROR = 'CONTINUE';

CREATE PIPE IF NOT EXISTS PIPE_OMS_ORDER
    AUTO_INGEST = TRUE
AS
COPY INTO ACME_EDP.RAW.RAW_OMS_ORDER (
    ORDER_ID, CUSTOMER_ID, ORDER_DATE, ORDER_STATUS, CHANNEL, CURRENCY, ORDER_AMOUNT,
    DISCOUNT_AMOUNT, SHIPPING_AMOUNT, CREATED_AT, UPDATED_AT, SRC_PAYLOAD,
    _SRC_SYSTEM, _SRC_FILE, _INGESTED_AT, _BATCH_ID, _CORRELATION_ID, _ROW_HASH
)
FROM (
    SELECT
        $1:orderId::VARCHAR, $1:customerId::VARCHAR, $1:orderDate::VARCHAR,
        $1:orderStatus::VARCHAR, $1:channel::VARCHAR, $1:currency::VARCHAR,
        $1:orderAmount::VARCHAR, $1:discountAmount::VARCHAR, $1:shippingAmount::VARCHAR,
        $1:createdAt::VARCHAR, $1:updatedAt::VARCHAR, $1,
        'OMS', METADATA$FILENAME, METADATA$START_SCAN_TIME,
        SPLIT_PART(METADATA$FILENAME, '/', -1), NULL, MD5(TO_JSON($1))
    FROM @STG_OMS
)
FILE_FORMAT = (FORMAT_NAME = FF_JSON)
ON_ERROR = 'CONTINUE';

CREATE PIPE IF NOT EXISTS PIPE_SUP_CASE
    AUTO_INGEST = TRUE
AS
COPY INTO ACME_EDP.RAW.RAW_SUP_CASE (
    CASE_ID, CUSTOMER_ID, CASE_TYPE, PRIORITY, SUBJECT, DESCRIPTION, STATUS, CHANNEL,
    OPENED_AT, RESOLVED_AT, RESOLUTION_NOTES, CSAT_SCORE, REOPEN_COUNT, SRC_PAYLOAD,
    _SRC_SYSTEM, _SRC_FILE, _INGESTED_AT, _BATCH_ID, _CORRELATION_ID, _ROW_HASH
)
FROM (
    SELECT
        $1:caseId::VARCHAR, $1:customerId::VARCHAR, $1:caseType::VARCHAR,
        $1:priority::VARCHAR, $1:subject::VARCHAR, $1:description::VARCHAR,
        $1:status::VARCHAR, $1:channel::VARCHAR, $1:openedAt::VARCHAR,
        $1:resolvedAt::VARCHAR, $1:resolutionNotes::VARCHAR, $1:csatScore::VARCHAR,
        $1:reopenCount::VARCHAR, $1,
        'SUPPORT', METADATA$FILENAME, METADATA$START_SCAN_TIME,
        SPLIT_PART(METADATA$FILENAME, '/', -1), NULL, MD5(TO_JSON($1))
    FROM @STG_SUPPORT
)
FILE_FORMAT = (FORMAT_NAME = FF_JSON)
ON_ERROR = 'CONTINUE';

-- Monitoring. A pipe that has silently stopped is the failure mode that goes
-- unnoticed for a week, because nothing errors - data simply stops arriving.
-- This view feeds the row-count-drift alert in docs/observability.md.
CREATE OR REPLACE VIEW ACME_EDP.GOVERNANCE.V_PIPE_HEALTH AS
SELECT
    PIPE_NAME,
    LAST_LOAD_TIME,
    DATEDIFF(minute, LAST_LOAD_TIME, CURRENT_TIMESTAMP()) AS MINUTES_SINCE_LAST_LOAD,
    NUM_ROWS_INSERTED,
    NUM_ROWS_PARSED,
    NUM_ROWS_PARSED - NUM_ROWS_INSERTED                   AS ROWS_REJECTED,
    FIRST_ERROR_MESSAGE
FROM SNOWFLAKE.ACCOUNT_USAGE.COPY_HISTORY
WHERE LAST_LOAD_TIME >= DATEADD(day, -7, CURRENT_TIMESTAMP());
