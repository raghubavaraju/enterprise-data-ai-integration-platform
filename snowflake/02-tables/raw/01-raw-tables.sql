-- =============================================================================
-- 02-RAW  Landing tables
-- =============================================================================
-- Rules for this layer:
--   * Column types are permissive (VARCHAR) so a source-side type change cannot
--     break ingestion.  Type enforcement happens in STAGING, where a failure is
--     recoverable without data loss.
--   * SRC_PAYLOAD keeps the untouched source record.  This is what makes schema
--     evolution survivable: a field added upstream lands in SRC_PAYLOAD on day
--     one and can be promoted to a typed column later, retrospectively.
--   * Audit columns are mandatory on every RAW table.  _CORRELATION_ID is the
--     same id MuleSoft generated at the edge, which is what allows a single
--     trace from API call to warehouse row (see docs/observability.md).
-- =============================================================================


CREATE TABLE IF NOT EXISTS ACME_EDP.RAW.RAW_CRM_CUSTOMER (
    CUSTOMER_ID              VARCHAR(64),
    SOURCE_SYSTEM            VARCHAR(32),
    FIRST_NAME               VARCHAR(200),
    LAST_NAME                VARCHAR(200),
    EMAIL                    VARCHAR(320),
    PHONE                    VARCHAR(64),
    BIRTH_DATE               VARCHAR(32),
    CUSTOMER_SEGMENT         VARCHAR(64),
    MARKETING_OPT_IN         VARCHAR(16),
    PREFERRED_CHANNEL        VARCHAR(64),
    STATUS                   VARCHAR(32),
    CREATED_AT               VARCHAR(64),
    UPDATED_AT               VARCHAR(64),
    SRC_PAYLOAD              VARIANT,
    _SRC_SYSTEM              VARCHAR(32),
    _SRC_FILE                VARCHAR(512),
    _INGESTED_AT             TIMESTAMP_NTZ,
    _BATCH_ID                VARCHAR(64),
    _CORRELATION_ID          VARCHAR(64),
    _ROW_HASH                VARCHAR(64)
) COMMENT = 'CRM customer master, as delivered. Never updated in place.';

CREATE TABLE IF NOT EXISTS ACME_EDP.RAW.RAW_CRM_CUSTOMER_ADDRESS (
    ADDRESS_ID               VARCHAR(64),
    CUSTOMER_ID              VARCHAR(64),
    ADDRESS_TYPE             VARCHAR(32),
    LINE1                    VARCHAR(300),
    LINE2                    VARCHAR(300),
    CITY                     VARCHAR(120),
    STATE                    VARCHAR(64),
    POSTAL_CODE              VARCHAR(32),
    COUNTRY                  VARCHAR(8),
    IS_PRIMARY               VARCHAR(16),
    VALID_FROM               VARCHAR(32),
    SRC_PAYLOAD              VARIANT,
    _SRC_SYSTEM              VARCHAR(32),
    _SRC_FILE                VARCHAR(512),
    _INGESTED_AT             TIMESTAMP_NTZ,
    _BATCH_ID                VARCHAR(64),
    _CORRELATION_ID          VARCHAR(64),
    _ROW_HASH                VARCHAR(64)
);

CREATE TABLE IF NOT EXISTS ACME_EDP.RAW.RAW_CRM_CUSTOMER_CONTACT (
    CONTACT_ID               VARCHAR(64),
    CUSTOMER_ID              VARCHAR(64),
    CONTACT_TYPE             VARCHAR(32),
    CONTACT_VALUE            VARCHAR(320),
    IS_VERIFIED              VARCHAR(16),
    IS_PRIMARY               VARCHAR(16),
    SRC_PAYLOAD              VARIANT,
    _SRC_SYSTEM              VARCHAR(32),
    _SRC_FILE                VARCHAR(512),
    _INGESTED_AT             TIMESTAMP_NTZ,
    _BATCH_ID                VARCHAR(64),
    _CORRELATION_ID          VARCHAR(64),
    _ROW_HASH                VARCHAR(64)
);

CREATE TABLE IF NOT EXISTS ACME_EDP.RAW.RAW_CRM_INTERACTION (
    INTERACTION_ID           VARCHAR(64),
    CUSTOMER_ID              VARCHAR(64),
    INTERACTION_TYPE         VARCHAR(64),
    CHANNEL                  VARCHAR(64),
    INTERACTION_TS           VARCHAR(64),
    CAMPAIGN_ID              VARCHAR(64),
    SRC_PAYLOAD              VARIANT,
    _SRC_SYSTEM              VARCHAR(32),
    _SRC_FILE                VARCHAR(512),
    _INGESTED_AT             TIMESTAMP_NTZ,
    _BATCH_ID                VARCHAR(64),
    _CORRELATION_ID          VARCHAR(64),
    _ROW_HASH                VARCHAR(64)
);

CREATE TABLE IF NOT EXISTS ACME_EDP.RAW.RAW_OMS_ORDER (
    ORDER_ID                 VARCHAR(64),
    CUSTOMER_ID              VARCHAR(64),
    ORDER_DATE               VARCHAR(32),
    ORDER_STATUS             VARCHAR(32),
    CHANNEL                  VARCHAR(64),
    CURRENCY                 VARCHAR(8),
    ORDER_AMOUNT             VARCHAR(32),
    DISCOUNT_AMOUNT          VARCHAR(32),
    SHIPPING_AMOUNT          VARCHAR(32),
    CREATED_AT               VARCHAR(64),
    UPDATED_AT               VARCHAR(64),
    SRC_PAYLOAD              VARIANT,
    _SRC_SYSTEM              VARCHAR(32),
    _SRC_FILE                VARCHAR(512),
    _INGESTED_AT             TIMESTAMP_NTZ,
    _BATCH_ID                VARCHAR(64),
    _CORRELATION_ID          VARCHAR(64),
    _ROW_HASH                VARCHAR(64)
);

CREATE TABLE IF NOT EXISTS ACME_EDP.RAW.RAW_OMS_ORDER_ITEM (
    ORDER_ITEM_ID            VARCHAR(64),
    ORDER_ID                 VARCHAR(64),
    PRODUCT_ID               VARCHAR(64),
    SKU                      VARCHAR(64),
    QUANTITY                 VARCHAR(32),
    UNIT_PRICE               VARCHAR(32),
    LINE_AMOUNT              VARCHAR(32),
    CURRENCY                 VARCHAR(8),
    SRC_PAYLOAD              VARIANT,
    _SRC_SYSTEM              VARCHAR(32),
    _SRC_FILE                VARCHAR(512),
    _INGESTED_AT             TIMESTAMP_NTZ,
    _BATCH_ID                VARCHAR(64),
    _CORRELATION_ID          VARCHAR(64),
    _ROW_HASH                VARCHAR(64)
);

CREATE TABLE IF NOT EXISTS ACME_EDP.RAW.RAW_PIM_PRODUCT (
    PRODUCT_ID               VARCHAR(64),
    SKU                      VARCHAR(64),
    PRODUCT_NAME             VARCHAR(300),
    CATEGORY                 VARCHAR(120),
    SUB_CATEGORY             VARCHAR(120),
    BRAND                    VARCHAR(120),
    UNIT_PRICE               VARCHAR(32),
    CURRENCY                 VARCHAR(8),
    IS_ACTIVE                VARCHAR(16),
    LAUNCH_DATE              VARCHAR(32),
    SRC_PAYLOAD              VARIANT,
    _SRC_SYSTEM              VARCHAR(32),
    _SRC_FILE                VARCHAR(512),
    _INGESTED_AT             TIMESTAMP_NTZ,
    _BATCH_ID                VARCHAR(64),
    _CORRELATION_ID          VARCHAR(64),
    _ROW_HASH                VARCHAR(64)
);

CREATE TABLE IF NOT EXISTS ACME_EDP.RAW.RAW_SUP_CASE (
    CASE_ID                  VARCHAR(64),
    CUSTOMER_ID              VARCHAR(64),
    CASE_TYPE                VARCHAR(64),
    PRIORITY                 VARCHAR(32),
    SUBJECT                  VARCHAR(500),
    DESCRIPTION              VARCHAR(16777216),
    STATUS                   VARCHAR(32),
    CHANNEL                  VARCHAR(64),
    OPENED_AT                VARCHAR(64),
    RESOLVED_AT              VARCHAR(64),
    RESOLUTION_NOTES         VARCHAR(16777216),
    CSAT_SCORE               VARCHAR(16),
    REOPEN_COUNT             VARCHAR(16),
    SRC_PAYLOAD              VARIANT,
    _SRC_SYSTEM              VARCHAR(32),
    _SRC_FILE                VARCHAR(512),
    _INGESTED_AT             TIMESTAMP_NTZ,
    _BATCH_ID                VARCHAR(64),
    _CORRELATION_ID          VARCHAR(64),
    _ROW_HASH                VARCHAR(64)
);

CREATE TABLE IF NOT EXISTS ACME_EDP.RAW.RAW_LOY_ACCOUNT (
    LOYALTY_ACCOUNT_ID       VARCHAR(64),
    CUSTOMER_ID              VARCHAR(64),
    TIER                     VARCHAR(32),
    POINTS_BALANCE           VARCHAR(32),
    POINTS_EARNED_LIFETIME   VARCHAR(32),
    POINTS_REDEEMED_LIFETIME VARCHAR(32),
    ENROLLED_AT              VARCHAR(64),
    LAST_ACTIVITY_AT         VARCHAR(64),
    STATUS                   VARCHAR(32),
    SRC_PAYLOAD              VARIANT,
    _SRC_SYSTEM              VARCHAR(32),
    _SRC_FILE                VARCHAR(512),
    _INGESTED_AT             TIMESTAMP_NTZ,
    _BATCH_ID                VARCHAR(64),
    _CORRELATION_ID          VARCHAR(64),
    _ROW_HASH                VARCHAR(64)
);

CREATE TABLE IF NOT EXISTS ACME_EDP.RAW.RAW_SUP_KNOWLEDGE_ARTICLE (
    ARTICLE_ID               VARCHAR(64),
    TITLE                    VARCHAR(500),
    CATEGORY                 VARCHAR(120),
    OWNER                    VARCHAR(200),
    LAST_REVIEWED            VARCHAR(32),
    SOURCE_URI               VARCHAR(1000),
    CONTENT                  VARCHAR(16777216),
    SRC_PAYLOAD              VARIANT,
    _SRC_SYSTEM              VARCHAR(32),
    _SRC_FILE                VARCHAR(512),
    _INGESTED_AT             TIMESTAMP_NTZ,
    _BATCH_ID                VARCHAR(64),
    _CORRELATION_ID          VARCHAR(64),
    _ROW_HASH                VARCHAR(64)
);

-- Quarantine.  Rows rejected by STAGING are moved here rather than dropped, so
-- that a data quality failure is a *recoverable* event with an audit trail
-- instead of silent data loss.  See snowflake/09-data-quality/.
CREATE TABLE IF NOT EXISTS ACME_EDP.RAW.RAW_REJECTED_RECORDS (
    REJECT_ID                VARCHAR(64),
    SOURCE_TABLE             VARCHAR(128),
    BUSINESS_KEY             VARCHAR(256),
    RULE_ID                  VARCHAR(64),
    RULE_SEVERITY            VARCHAR(16),
    REJECT_REASON            VARCHAR(2000),
    SRC_PAYLOAD              VARIANT,
    _BATCH_ID                VARCHAR(64),
    _CORRELATION_ID          VARCHAR(64),
    _REJECTED_AT             TIMESTAMP_NTZ
) COMMENT = 'Dead-letter table for records that fail blocking data quality rules.';
