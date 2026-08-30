-- =============================================================================
-- 02-ANALYTICS  Consumption-shaped models
-- =============================================================================
-- CUSTOMER_360 is *materialised*, not a view.  Three reasons:
--   1. Latency budget - the Experience API has a p95 target of 800 ms and the
--      view version joins eight tables with window functions.
--   2. Cost - a view recomputes on every API call; the table is computed once
--      per load and read many times.
--   3. Stability - AI insights and churn scores must be reproducible against a
--      known snapshot.  A view that changes under the model's feet makes an
--      explanation unauditable.
-- The trade-off is freshness, which is why AS_OF_TIMESTAMP is part of the API
-- response and the SLA is stated in docs/data-architecture.md.
-- =============================================================================


CREATE TABLE IF NOT EXISTS ACME_EDP.ANALYTICS.CUSTOMER_ORDER_SUMMARY (
    CUSTOMER_BK              VARCHAR(64) NOT NULL,
    FIRST_ORDER_DATE         DATE,
    LAST_ORDER_DATE          DATE,
    DAYS_SINCE_LAST_ORDER    NUMBER(9,0),
    TOTAL_ORDERS             NUMBER(12,0),
    COMPLETED_ORDERS         NUMBER(12,0),
    CANCELLED_ORDERS         NUMBER(12,0),
    RETURNED_ORDERS          NUMBER(12,0),
    TOTAL_NET_REVENUE        NUMBER(18,2),
    AVG_ORDER_VALUE          NUMBER(18,2),
    MAX_ORDER_VALUE          NUMBER(18,2),
    ORDERS_LAST_90D          NUMBER(12,0),
    REVENUE_LAST_90D         NUMBER(18,2),
    ORDERS_LAST_365D         NUMBER(12,0),
    REVENUE_LAST_365D        NUMBER(18,2),
    ORDER_FREQUENCY_PER_YEAR NUMBER(12,4),
    DISTINCT_CATEGORIES      NUMBER(9,0),
    PRIMARY_CHANNEL          VARCHAR(64),
    RETURN_RATE              NUMBER(9,4),
    AS_OF_DATE               DATE,
    _LOADED_AT               TIMESTAMP_NTZ
);

CREATE TABLE IF NOT EXISTS ACME_EDP.ANALYTICS.CUSTOMER_SUPPORT_SUMMARY (
    CUSTOMER_BK              VARCHAR(64) NOT NULL,
    TOTAL_CASES              NUMBER(12,0),
    OPEN_CASES               NUMBER(12,0),
    CASES_LAST_90D           NUMBER(12,0),
    CASES_LAST_365D          NUMBER(12,0),
    AVG_CSAT                 NUMBER(5,2),
    MIN_CSAT                 NUMBER(3,0),
    AVG_RESOLUTION_HOURS     NUMBER(12,2),
    TOTAL_REOPENS            NUMBER(12,0),
    SLA_BREACHES             NUMBER(12,0),
    TOP_CASE_TYPE            VARCHAR(64),
    LAST_CASE_DATE           DATE,
    DAYS_SINCE_LAST_CASE     NUMBER(9,0),
    AS_OF_DATE               DATE,
    _LOADED_AT               TIMESTAMP_NTZ
);

CREATE TABLE IF NOT EXISTS ACME_EDP.ANALYTICS.CUSTOMER_ENGAGEMENT_SUMMARY (
    CUSTOMER_BK              VARCHAR(64) NOT NULL,
    INTERACTIONS_LAST_90D    NUMBER(12,0),
    INTERACTIONS_LAST_365D   NUMBER(12,0),
    NEGATIVE_SIGNALS_90D     NUMBER(12,0),
    LAST_INTERACTION_DATE    DATE,
    DAYS_SINCE_INTERACTION   NUMBER(9,0),
    DISTINCT_CHANNELS        NUMBER(9,0),
    ENGAGEMENT_SCORE         NUMBER(5,2),   -- 0-100, derived in 07-02; single
                                            -- definition reused by CUSTOMER_360
                                            -- and by the AI feature store
    AS_OF_DATE               DATE,
    _LOADED_AT               TIMESTAMP_NTZ
);

CREATE TABLE IF NOT EXISTS ACME_EDP.ANALYTICS.CUSTOMER_360 (
    -- identity ------------------------------------------------------------
    CUSTOMER_BK              VARCHAR(64)  NOT NULL,
    CUSTOMER_SK              VARCHAR(64),
    MASTER_CUSTOMER_ID       VARCHAR(64),
    -- profile -------------------------------------------------------------
    FULL_NAME                VARCHAR(400),
    EMAIL                    VARCHAR(320),
    PHONE                    VARCHAR(64),
    BIRTH_DATE               DATE,
    CUSTOMER_SEGMENT         VARCHAR(64),
    PREFERRED_CHANNEL        VARCHAR(64),
    MARKETING_OPT_IN         BOOLEAN,
    CUSTOMER_STATUS          VARCHAR(32),
    CUSTOMER_SINCE           DATE,
    TENURE_DAYS              NUMBER(9,0),
    PRIMARY_CITY             VARCHAR(120),
    PRIMARY_STATE            VARCHAR(64),
    PRIMARY_COUNTRY          VARCHAR(8),
    -- purchase ------------------------------------------------------------
    TOTAL_ORDERS             NUMBER(12,0),
    TOTAL_NET_REVENUE        NUMBER(18,2),
    AVG_ORDER_VALUE          NUMBER(18,2),
    ORDER_FREQUENCY_PER_YEAR NUMBER(12,4),
    LAST_ORDER_DATE          DATE,
    DAYS_SINCE_LAST_ORDER    NUMBER(9,0),
    REVENUE_LAST_365D        NUMBER(18,2),
    RETURN_RATE              NUMBER(9,4),
    PRIMARY_ORDER_CHANNEL    VARCHAR(64),
    -- service -------------------------------------------------------------
    TOTAL_CASES              NUMBER(12,0),
    OPEN_CASES               NUMBER(12,0),
    CASES_LAST_90D           NUMBER(12,0),
    AVG_CSAT                 NUMBER(5,2),
    AVG_RESOLUTION_HOURS     NUMBER(12,2),
    TOP_CASE_TYPE            VARCHAR(64),
    -- loyalty -------------------------------------------------------------
    LOYALTY_ACCOUNT_BK       VARCHAR(64),
    LOYALTY_TIER             VARCHAR(32),
    LOYALTY_STATUS           VARCHAR(32),
    LOYALTY_POINTS_BALANCE   NUMBER(18,0),
    LOYALTY_ENROLLED_AT      DATE,
    DAYS_SINCE_LOYALTY_ACTIVITY NUMBER(9,0),
    -- engagement ----------------------------------------------------------
    INTERACTIONS_LAST_90D    NUMBER(12,0),
    NEGATIVE_SIGNALS_90D     NUMBER(12,0),
    ENGAGEMENT_SCORE         NUMBER(5,2),   -- 0-100, deterministic, see 07-
    -- value ---------------------------------------------------------------
    CUSTOMER_LIFETIME_VALUE  NUMBER(18,2),
    PREDICTED_CLV_12M        NUMBER(18,2),
    VALUE_TIER               VARCHAR(16),   -- HIGH | MEDIUM | LOW
    -- governance ----------------------------------------------------------
    DATA_COMPLETENESS_SCORE  NUMBER(5,2),
    CONTRIBUTING_SOURCES     VARCHAR(200),
    AS_OF_TIMESTAMP          TIMESTAMP_NTZ,
    _BATCH_ID                VARCHAR(64),
    _CORRELATION_ID          VARCHAR(64),
    _LOADED_AT               TIMESTAMP_NTZ,
    CONSTRAINT PK_CUSTOMER_360 PRIMARY KEY (CUSTOMER_BK)
) COMMENT = 'Unified customer view. One row per customer. Rebuilt each load.';
