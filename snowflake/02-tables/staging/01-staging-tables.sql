-- =============================================================================
-- 02-STAGING  Typed, cleansed, deduplicated
-- =============================================================================
-- STAGING is disposable.  It can always be rebuilt from RAW, which means a bug
-- in cleansing logic is fixed by re-running, not by a data recovery exercise.
-- Every STG table carries DQ_STATUS so that downstream loads can choose to
-- exclude or flag rows without a second pass over the data.
-- =============================================================================


CREATE TABLE IF NOT EXISTS ACME_EDP.STAGING.STG_CUSTOMER (
    CUSTOMER_BK              VARCHAR(64)   NOT NULL,   -- business key from CRM
    SOURCE_SYSTEM            VARCHAR(32)   NOT NULL,
    FIRST_NAME               VARCHAR(200),
    LAST_NAME                VARCHAR(200),
    FULL_NAME                VARCHAR(400),
    EMAIL                    VARCHAR(320),
    EMAIL_IS_VALID           BOOLEAN,
    PHONE                    VARCHAR(64),
    BIRTH_DATE               DATE,
    CUSTOMER_SEGMENT         VARCHAR(64),
    MARKETING_OPT_IN         BOOLEAN,
    PREFERRED_CHANNEL        VARCHAR(64),
    STATUS                   VARCHAR(32),
    SOURCE_CREATED_AT        TIMESTAMP_NTZ,
    SOURCE_UPDATED_AT        TIMESTAMP_NTZ,
    MATCH_KEY                VARCHAR(64),              -- fuzzy-duplicate grouping key
    DQ_STATUS                VARCHAR(16),              -- PASS | WARN | FAIL
    DQ_FAILED_RULES          VARCHAR(1000),
    _BATCH_ID                VARCHAR(64),
    _CORRELATION_ID          VARCHAR(64),
    _LOADED_AT               TIMESTAMP_NTZ,
    _ROW_HASH                VARCHAR(64)
);

CREATE TABLE IF NOT EXISTS ACME_EDP.STAGING.STG_CUSTOMER_ADDRESS (
    ADDRESS_BK               VARCHAR(64) NOT NULL,
    CUSTOMER_BK              VARCHAR(64) NOT NULL,
    ADDRESS_TYPE             VARCHAR(32),
    LINE1                    VARCHAR(300),
    LINE2                    VARCHAR(300),
    CITY                     VARCHAR(120),
    STATE                    VARCHAR(64),
    POSTAL_CODE              VARCHAR(32),
    COUNTRY                  VARCHAR(8),
    IS_PRIMARY               BOOLEAN,
    VALID_FROM               DATE,
    DQ_STATUS                VARCHAR(16),
    _BATCH_ID                VARCHAR(64),
    _LOADED_AT               TIMESTAMP_NTZ
);

CREATE TABLE IF NOT EXISTS ACME_EDP.STAGING.STG_CUSTOMER_CONTACT (
    CONTACT_BK               VARCHAR(64) NOT NULL,
    CUSTOMER_BK              VARCHAR(64) NOT NULL,
    CONTACT_TYPE             VARCHAR(32),
    CONTACT_VALUE            VARCHAR(320),
    IS_VERIFIED              BOOLEAN,
    IS_PRIMARY               BOOLEAN,
    DQ_STATUS                VARCHAR(16),
    _BATCH_ID                VARCHAR(64),
    _LOADED_AT               TIMESTAMP_NTZ
);

CREATE TABLE IF NOT EXISTS ACME_EDP.STAGING.STG_SALES_ORDER (
    ORDER_BK                 VARCHAR(64) NOT NULL,
    CUSTOMER_BK              VARCHAR(64),
    ORDER_DATE               DATE,
    ORDER_STATUS             VARCHAR(32),
    CHANNEL                  VARCHAR(64),
    CURRENCY_CODE            VARCHAR(8),
    ORDER_AMOUNT             NUMBER(18,2),
    DISCOUNT_AMOUNT          NUMBER(18,2),
    SHIPPING_AMOUNT          NUMBER(18,2),
    NET_AMOUNT               NUMBER(18,2),
    SOURCE_CREATED_AT        TIMESTAMP_NTZ,
    SOURCE_UPDATED_AT        TIMESTAMP_NTZ,
    DQ_STATUS                VARCHAR(16),
    DQ_FAILED_RULES          VARCHAR(1000),
    _BATCH_ID                VARCHAR(64),
    _CORRELATION_ID          VARCHAR(64),
    _LOADED_AT               TIMESTAMP_NTZ
);

CREATE TABLE IF NOT EXISTS ACME_EDP.STAGING.STG_SALES_ORDER_ITEM (
    ORDER_ITEM_BK            VARCHAR(64) NOT NULL,
    ORDER_BK                 VARCHAR(64) NOT NULL,
    PRODUCT_BK               VARCHAR(64),
    SKU                      VARCHAR(64),
    QUANTITY                 NUMBER(12,0),
    UNIT_PRICE               NUMBER(18,2),
    LINE_AMOUNT              NUMBER(18,2),
    CURRENCY_CODE            VARCHAR(8),
    DQ_STATUS                VARCHAR(16),
    _BATCH_ID                VARCHAR(64),
    _LOADED_AT               TIMESTAMP_NTZ
);

CREATE TABLE IF NOT EXISTS ACME_EDP.STAGING.STG_PRODUCT (
    PRODUCT_BK               VARCHAR(64) NOT NULL,
    SKU                      VARCHAR(64),
    PRODUCT_NAME             VARCHAR(300),
    CATEGORY                 VARCHAR(120),
    SUB_CATEGORY             VARCHAR(120),
    BRAND                    VARCHAR(120),
    UNIT_PRICE               NUMBER(18,2),
    CURRENCY_CODE            VARCHAR(8),
    IS_ACTIVE                BOOLEAN,
    LAUNCH_DATE              DATE,
    DQ_STATUS                VARCHAR(16),
    _BATCH_ID                VARCHAR(64),
    _LOADED_AT               TIMESTAMP_NTZ
);

CREATE TABLE IF NOT EXISTS ACME_EDP.STAGING.STG_SUPPORT_CASE (
    CASE_BK                  VARCHAR(64) NOT NULL,
    CUSTOMER_BK              VARCHAR(64),
    CASE_TYPE                VARCHAR(64),
    PRIORITY                 VARCHAR(32),
    SUBJECT                  VARCHAR(500),
    DESCRIPTION              VARCHAR(16777216),
    STATUS                   VARCHAR(32),
    CHANNEL                  VARCHAR(64),
    OPENED_AT                TIMESTAMP_NTZ,
    RESOLVED_AT              TIMESTAMP_NTZ,
    RESOLUTION_HOURS         NUMBER(12,2),
    RESOLUTION_NOTES         VARCHAR(16777216),
    CSAT_SCORE               NUMBER(3,0),
    REOPEN_COUNT             NUMBER(5,0),
    DQ_STATUS                VARCHAR(16),
    _BATCH_ID                VARCHAR(64),
    _LOADED_AT               TIMESTAMP_NTZ
);

CREATE TABLE IF NOT EXISTS ACME_EDP.STAGING.STG_CUSTOMER_INTERACTION (
    INTERACTION_BK           VARCHAR(64) NOT NULL,
    CUSTOMER_BK              VARCHAR(64),
    INTERACTION_TYPE         VARCHAR(64),
    CHANNEL                  VARCHAR(64),
    INTERACTION_TS           TIMESTAMP_NTZ,
    CAMPAIGN_ID              VARCHAR(64),
    DQ_STATUS                VARCHAR(16),
    _BATCH_ID                VARCHAR(64),
    _LOADED_AT               TIMESTAMP_NTZ
);

CREATE TABLE IF NOT EXISTS ACME_EDP.STAGING.STG_LOYALTY_ACCOUNT (
    LOYALTY_ACCOUNT_BK       VARCHAR(64) NOT NULL,
    CUSTOMER_BK              VARCHAR(64),
    TIER                     VARCHAR(32),
    POINTS_BALANCE           NUMBER(18,0),
    POINTS_EARNED_LIFETIME   NUMBER(18,0),
    POINTS_REDEEMED_LIFETIME NUMBER(18,0),
    ENROLLED_AT              DATE,
    LAST_ACTIVITY_AT         DATE,
    STATUS                   VARCHAR(32),
    DQ_STATUS                VARCHAR(16),
    _BATCH_ID                VARCHAR(64),
    _LOADED_AT               TIMESTAMP_NTZ
);
