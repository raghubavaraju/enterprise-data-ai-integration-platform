-- =============================================================================
-- 03-01  CORE views      [portable]
-- =============================================================================
-- These exist so that no downstream object ever writes "WHERE IS_CURRENT = TRUE"
-- itself.  Forgetting that predicate on an SCD2 table silently multiplies every
-- metric by the number of versions - a bug that is invisible in a small dev
-- dataset and catastrophic in production.
-- =============================================================================

CREATE OR REPLACE VIEW ACME_EDP.CORE.V_CUSTOMER_CURRENT AS
SELECT
    CUSTOMER_SK, CUSTOMER_BK, MASTER_CUSTOMER_ID, SOURCE_SYSTEM, FIRST_NAME, LAST_NAME,
    FULL_NAME, EMAIL, PHONE, BIRTH_DATE, CUSTOMER_SEGMENT, MARKETING_OPT_IN,
    PREFERRED_CHANNEL, STATUS, SOURCE_CREATED_AT, VALID_FROM, VERSION_NUMBER
FROM ACME_EDP.CORE.CUSTOMER
WHERE IS_CURRENT = TRUE;

-- Point-in-time lookup.  The reason CUSTOMER is Type 2 at all: answering
-- "what was true about this customer when that happened?".
CREATE OR REPLACE VIEW ACME_EDP.CORE.V_CUSTOMER_HISTORY AS
SELECT
    CUSTOMER_BK, VERSION_NUMBER, VALID_FROM, VALID_TO, IS_CURRENT, CHANGE_TYPE,
    CUSTOMER_SEGMENT, STATUS, MARKETING_OPT_IN, EMAIL, PREFERRED_CHANNEL,
    LAG(CUSTOMER_SEGMENT) OVER (PARTITION BY CUSTOMER_BK ORDER BY VALID_FROM)
        AS PREVIOUS_SEGMENT,
    LAG(MARKETING_OPT_IN) OVER (PARTITION BY CUSTOMER_BK ORDER BY VALID_FROM)
        AS PREVIOUS_MARKETING_OPT_IN
FROM ACME_EDP.CORE.CUSTOMER;

-- Consent history is a compliance artefact, not an analytics convenience: on a
-- subject access or marketing-audit request, this is the evidence.
CREATE OR REPLACE VIEW ACME_EDP.CORE.V_MARKETING_CONSENT_HISTORY AS
SELECT
    CUSTOMER_BK, VALID_FROM AS CONSENT_FROM, VALID_TO AS CONSENT_TO,
    MARKETING_OPT_IN AS CONSENT_GRANTED, VERSION_NUMBER, SOURCE_SYSTEM
FROM ACME_EDP.CORE.CUSTOMER;

CREATE OR REPLACE VIEW ACME_EDP.CORE.V_ORDER_ENRICHED AS
SELECT
    o.ORDER_BK, o.CUSTOMER_BK, o.ORDER_DATE, o.ORDER_STATUS, o.CHANNEL,
    o.CURRENCY_CODE, o.NET_AMOUNT, o.IS_REVENUE_RECOGNISED,
    i.ORDER_ITEM_BK, i.PRODUCT_BK, i.QUANTITY, i.UNIT_PRICE, i.LINE_AMOUNT,
    p.PRODUCT_NAME, p.CATEGORY, p.SUB_CATEGORY, p.BRAND
FROM ACME_EDP.CORE.SALES_ORDER o
LEFT JOIN ACME_EDP.CORE.SALES_ORDER_ITEM i ON i.ORDER_BK   = o.ORDER_BK
LEFT JOIN ACME_EDP.CORE.PRODUCT          p ON p.PRODUCT_BK = i.PRODUCT_BK;
