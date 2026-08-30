-- =============================================================================
-- 02-CORE  Conformed enterprise entities
-- =============================================================================
-- Modelling decisions worth defending in review:
--
-- 1. CUSTOMER is a Type 2 slowly changing dimension.  Segment, status and
--    marketing consent all change, and every downstream question ("what tier
--    was this customer in when the order was placed?", "did they consent at the
--    time we mailed them?") is unanswerable without history.  Consent history
--    in particular is a regulatory requirement, not an analytics nicety.
--
-- 2. Surrogate keys are deterministic hashes, not sequences.  A hash key can be
--    computed independently in any layer, in any order, and after a reload -
--    a sequence cannot, and reload-order dependence is the classic cause of
--    silently broken joins in a rebuilt warehouse.
--
-- 3. Primary and foreign keys are declared but NOT ENFORCED by Snowflake.  They
--    are declared anyway because they document intent, drive the ER diagram,
--    and let the optimiser eliminate joins.  Enforcement is done by the data
--    quality rules in snowflake/09-data-quality/, which is the honest place for
--    it in an analytical store.
--
-- 4. SALES_ORDER, not ORDER: ORDER is a reserved word.
-- =============================================================================


-- ------------------------------------------------------------------ CUSTOMER
CREATE TABLE IF NOT EXISTS ACME_EDP.CORE.CUSTOMER (
    CUSTOMER_SK              VARCHAR(64)  NOT NULL,   -- MD5(CUSTOMER_BK || VALID_FROM)
    CUSTOMER_BK              VARCHAR(64)  NOT NULL,   -- CRM business key
    MASTER_CUSTOMER_ID       VARCHAR(64),             -- survivorship winner after matching
    SOURCE_SYSTEM            VARCHAR(32)  NOT NULL,
    FIRST_NAME               VARCHAR(200),
    LAST_NAME                VARCHAR(200),
    FULL_NAME                VARCHAR(400),
    EMAIL                    VARCHAR(320),
    PHONE                    VARCHAR(64),
    BIRTH_DATE               DATE,
    CUSTOMER_SEGMENT         VARCHAR(64),
    MARKETING_OPT_IN         BOOLEAN,
    PREFERRED_CHANNEL        VARCHAR(64),
    STATUS                   VARCHAR(32),
    SOURCE_CREATED_AT        TIMESTAMP_NTZ,
    -- SCD2 control columns
    VALID_FROM               TIMESTAMP_NTZ NOT NULL,
    VALID_TO                 TIMESTAMP_NTZ NOT NULL,   -- 9999-12-31 for the open row
    IS_CURRENT               BOOLEAN       NOT NULL,
    VERSION_NUMBER           NUMBER(9,0)   NOT NULL,
    CHANGE_TYPE              VARCHAR(16),              -- INSERT | UPDATE | DELETE
    _ROW_HASH                VARCHAR(64),              -- hash of tracked attributes
    _BATCH_ID                VARCHAR(64),
    _CORRELATION_ID          VARCHAR(64),
    _LOADED_AT               TIMESTAMP_NTZ,
    CONSTRAINT PK_CUSTOMER PRIMARY KEY (CUSTOMER_SK)
) COMMENT = 'Enterprise customer dimension, Type 2. One row per version.';

CREATE TABLE IF NOT EXISTS ACME_EDP.CORE.CUSTOMER_ADDRESS (
    ADDRESS_SK               VARCHAR(64) NOT NULL,
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
    _BATCH_ID                VARCHAR(64),
    _LOADED_AT               TIMESTAMP_NTZ,
    CONSTRAINT PK_CUSTOMER_ADDRESS PRIMARY KEY (ADDRESS_SK)
);

CREATE TABLE IF NOT EXISTS ACME_EDP.CORE.CUSTOMER_CONTACT (
    CONTACT_SK               VARCHAR(64) NOT NULL,
    CONTACT_BK               VARCHAR(64) NOT NULL,
    CUSTOMER_BK              VARCHAR(64) NOT NULL,
    CONTACT_TYPE             VARCHAR(32),
    CONTACT_VALUE            VARCHAR(320),
    IS_VERIFIED              BOOLEAN,
    IS_PRIMARY               BOOLEAN,
    _BATCH_ID                VARCHAR(64),
    _LOADED_AT               TIMESTAMP_NTZ,
    CONSTRAINT PK_CUSTOMER_CONTACT PRIMARY KEY (CONTACT_SK)
);

-- --------------------------------------------------------------------- ORDER
CREATE TABLE IF NOT EXISTS ACME_EDP.CORE.SALES_ORDER (
    ORDER_SK                 VARCHAR(64) NOT NULL,
    ORDER_BK                 VARCHAR(64) NOT NULL,
    CUSTOMER_BK              VARCHAR(64),
    CUSTOMER_SK              VARCHAR(64),   -- points at the customer version
                                            -- current *at the time of the order*
    ORDER_DATE               DATE,
    ORDER_STATUS             VARCHAR(32),
    CHANNEL                  VARCHAR(64),
    CURRENCY_CODE            VARCHAR(8),
    ORDER_AMOUNT             NUMBER(18,2),
    DISCOUNT_AMOUNT          NUMBER(18,2),
    SHIPPING_AMOUNT          NUMBER(18,2),
    NET_AMOUNT               NUMBER(18,2),
    IS_REVENUE_RECOGNISED    BOOLEAN,       -- COMPLETED/SHIPPED only
    SOURCE_CREATED_AT        TIMESTAMP_NTZ,
    SOURCE_UPDATED_AT        TIMESTAMP_NTZ,
    _BATCH_ID                VARCHAR(64),
    _CORRELATION_ID          VARCHAR(64),
    _LOADED_AT               TIMESTAMP_NTZ,
    CONSTRAINT PK_SALES_ORDER PRIMARY KEY (ORDER_SK)
);

CREATE TABLE IF NOT EXISTS ACME_EDP.CORE.SALES_ORDER_ITEM (
    ORDER_ITEM_SK            VARCHAR(64) NOT NULL,
    ORDER_ITEM_BK            VARCHAR(64) NOT NULL,
    ORDER_BK                 VARCHAR(64) NOT NULL,
    PRODUCT_BK               VARCHAR(64),
    SKU                      VARCHAR(64),
    QUANTITY                 NUMBER(12,0),
    UNIT_PRICE               NUMBER(18,2),
    LINE_AMOUNT              NUMBER(18,2),
    CURRENCY_CODE            VARCHAR(8),
    _BATCH_ID                VARCHAR(64),
    _LOADED_AT               TIMESTAMP_NTZ,
    CONSTRAINT PK_SALES_ORDER_ITEM PRIMARY KEY (ORDER_ITEM_SK)
);

CREATE TABLE IF NOT EXISTS ACME_EDP.CORE.PRODUCT (
    PRODUCT_SK               VARCHAR(64) NOT NULL,
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
    _BATCH_ID                VARCHAR(64),
    _LOADED_AT               TIMESTAMP_NTZ,
    CONSTRAINT PK_PRODUCT PRIMARY KEY (PRODUCT_SK)
);

-- ---------------------------------------------------------- SERVICE / LOYALTY
CREATE TABLE IF NOT EXISTS ACME_EDP.CORE.SUPPORT_CASE (
    CASE_SK                  VARCHAR(64) NOT NULL,
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
    IS_SLA_BREACHED          BOOLEAN,
    _BATCH_ID                VARCHAR(64),
    _LOADED_AT               TIMESTAMP_NTZ,
    CONSTRAINT PK_SUPPORT_CASE PRIMARY KEY (CASE_SK)
);

CREATE TABLE IF NOT EXISTS ACME_EDP.CORE.CUSTOMER_INTERACTION (
    INTERACTION_SK           VARCHAR(64) NOT NULL,
    INTERACTION_BK           VARCHAR(64) NOT NULL,
    CUSTOMER_BK              VARCHAR(64),
    INTERACTION_TYPE         VARCHAR(64),
    CHANNEL                  VARCHAR(64),
    INTERACTION_TS           TIMESTAMP_NTZ,
    CAMPAIGN_ID              VARCHAR(64),
    IS_NEGATIVE_SIGNAL       BOOLEAN,   -- unsubscribe / cart abandonment
    _BATCH_ID                VARCHAR(64),
    _LOADED_AT               TIMESTAMP_NTZ,
    CONSTRAINT PK_CUSTOMER_INTERACTION PRIMARY KEY (INTERACTION_SK)
);

CREATE TABLE IF NOT EXISTS ACME_EDP.CORE.LOYALTY_ACCOUNT (
    LOYALTY_ACCOUNT_SK       VARCHAR(64) NOT NULL,
    LOYALTY_ACCOUNT_BK       VARCHAR(64) NOT NULL,
    CUSTOMER_BK              VARCHAR(64),
    TIER                     VARCHAR(32),
    TIER_RANK                NUMBER(2,0),
    POINTS_BALANCE           NUMBER(18,0),
    POINTS_EARNED_LIFETIME   NUMBER(18,0),
    POINTS_REDEEMED_LIFETIME NUMBER(18,0),
    ENROLLED_AT              DATE,
    LAST_ACTIVITY_AT         DATE,
    STATUS                   VARCHAR(32),
    _BATCH_ID                VARCHAR(64),
    _LOADED_AT               TIMESTAMP_NTZ,
    CONSTRAINT PK_LOYALTY_ACCOUNT PRIMARY KEY (LOYALTY_ACCOUNT_SK)
);
