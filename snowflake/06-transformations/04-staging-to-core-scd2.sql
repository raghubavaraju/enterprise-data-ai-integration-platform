-- =============================================================================
-- 06-04  STAGING -> CORE : full rebuild (SCD Type 2 aware)      [portable]
-- =============================================================================
-- This is the *full-refresh* path.  It rebuilds CORE.CUSTOMER while preserving
-- existing history: rows already closed stay closed, the open row is closed and
-- superseded only when the tracked-attribute hash actually changed.
--
-- The incremental path - which is what runs on a schedule in Snowflake - is
-- 05-pipelines/03-incremental-scd2-merge.sql and uses MERGE over a stream.
-- Both produce the same end state; this one exists so the local warehouse and
-- the tests can rebuild from nothing and so a corrupted CORE can be recovered
-- from RAW without a restore.
--
-- Effective-dating rule: VALID_FROM is the *source* update timestamp, not the
-- load timestamp.  Using load time would make history depend on when the
-- pipeline happened to run, which makes point-in-time answers wrong after any
-- backfill.
-- =============================================================================

-- Step 1: close the currently-open version of every customer whose tracked
-- attributes have changed.
UPDATE ACME_EDP.CORE.CUSTOMER AS c
SET VALID_TO = COALESCE(
        (SELECT s.SOURCE_UPDATED_AT FROM ACME_EDP.STAGING.STG_CUSTOMER s
          WHERE s.CUSTOMER_BK = c.CUSTOMER_BK),
        CURRENT_TIMESTAMP),
    IS_CURRENT = FALSE,
    CHANGE_TYPE = 'UPDATE'
WHERE c.IS_CURRENT = TRUE
  AND EXISTS (
        SELECT 1 FROM ACME_EDP.STAGING.STG_CUSTOMER s
         WHERE s.CUSTOMER_BK = c.CUSTOMER_BK
           AND s._ROW_HASH <> c._ROW_HASH);

-- Step 2: insert a new open version for new customers and for changed ones.
INSERT INTO ACME_EDP.CORE.CUSTOMER (
    CUSTOMER_SK, CUSTOMER_BK, MASTER_CUSTOMER_ID, SOURCE_SYSTEM, FIRST_NAME, LAST_NAME,
    FULL_NAME, EMAIL, PHONE, BIRTH_DATE, CUSTOMER_SEGMENT, MARKETING_OPT_IN,
    PREFERRED_CHANNEL, STATUS, SOURCE_CREATED_AT, VALID_FROM, VALID_TO, IS_CURRENT,
    VERSION_NUMBER, CHANGE_TYPE, _ROW_HASH, _BATCH_ID, _CORRELATION_ID, _LOADED_AT
)
SELECT
    MD5(s.CUSTOMER_BK || '|' || CAST(COALESCE(s.SOURCE_UPDATED_AT,
                                              CURRENT_TIMESTAMP) AS VARCHAR)) AS CUSTOMER_SK,
    s.CUSTOMER_BK,
    s.CUSTOMER_BK                                        AS MASTER_CUSTOMER_ID,
    s.SOURCE_SYSTEM, s.FIRST_NAME, s.LAST_NAME, s.FULL_NAME, s.EMAIL, s.PHONE,
    s.BIRTH_DATE, s.CUSTOMER_SEGMENT, s.MARKETING_OPT_IN, s.PREFERRED_CHANNEL, s.STATUS,
    s.SOURCE_CREATED_AT,
    COALESCE(s.SOURCE_UPDATED_AT, s.SOURCE_CREATED_AT, CURRENT_TIMESTAMP) AS VALID_FROM,
    TIMESTAMP '9999-12-31 00:00:00'                      AS VALID_TO,
    TRUE                                                 AS IS_CURRENT,
    COALESCE((SELECT MAX(c2.VERSION_NUMBER) FROM ACME_EDP.CORE.CUSTOMER c2
               WHERE c2.CUSTOMER_BK = s.CUSTOMER_BK), 0) + 1 AS VERSION_NUMBER,
    CASE WHEN EXISTS (SELECT 1 FROM ACME_EDP.CORE.CUSTOMER c3
                       WHERE c3.CUSTOMER_BK = s.CUSTOMER_BK)
         THEN 'UPDATE' ELSE 'INSERT' END                 AS CHANGE_TYPE,
    s._ROW_HASH, s._BATCH_ID, s._CORRELATION_ID, CURRENT_TIMESTAMP
FROM ACME_EDP.STAGING.STG_CUSTOMER s
WHERE s.DQ_STATUS <> 'FAIL'
  AND NOT EXISTS (
        SELECT 1 FROM ACME_EDP.CORE.CUSTOMER c
         WHERE c.CUSTOMER_BK = s.CUSTOMER_BK
           AND c.IS_CURRENT = TRUE
           AND c._ROW_HASH = s._ROW_HASH);

-- ------------------------------------------------------- Type 1 / transactional
-- Addresses, contacts, products, orders, cases, interactions and loyalty are
-- rebuilt and not historised.  Justification: they are either transactional
-- facts (immutable once complete) or attributes whose history nobody has asked
-- a question about.  Historising everything "just in case" is the most common
-- way to make a warehouse both expensive and unqueryable.
DELETE FROM ACME_EDP.CORE.CUSTOMER_ADDRESS;
INSERT INTO ACME_EDP.CORE.CUSTOMER_ADDRESS
SELECT MD5(ADDRESS_BK), ADDRESS_BK, CUSTOMER_BK, ADDRESS_TYPE, LINE1, LINE2, CITY, STATE,
       POSTAL_CODE, COUNTRY, IS_PRIMARY, VALID_FROM, _BATCH_ID, CURRENT_TIMESTAMP
FROM ACME_EDP.STAGING.STG_CUSTOMER_ADDRESS
WHERE DQ_STATUS <> 'FAIL';

DELETE FROM ACME_EDP.CORE.CUSTOMER_CONTACT;
INSERT INTO ACME_EDP.CORE.CUSTOMER_CONTACT
SELECT MD5(CONTACT_BK), CONTACT_BK, CUSTOMER_BK, CONTACT_TYPE, CONTACT_VALUE,
       IS_VERIFIED, IS_PRIMARY, _BATCH_ID, CURRENT_TIMESTAMP
FROM ACME_EDP.STAGING.STG_CUSTOMER_CONTACT
WHERE DQ_STATUS <> 'FAIL';

DELETE FROM ACME_EDP.CORE.PRODUCT;
INSERT INTO ACME_EDP.CORE.PRODUCT
SELECT MD5(PRODUCT_BK), PRODUCT_BK, SKU, PRODUCT_NAME, CATEGORY, SUB_CATEGORY, BRAND,
       UNIT_PRICE, CURRENCY_CODE, IS_ACTIVE, LAUNCH_DATE, _BATCH_ID, CURRENT_TIMESTAMP
FROM ACME_EDP.STAGING.STG_PRODUCT
WHERE DQ_STATUS <> 'FAIL';

DELETE FROM ACME_EDP.CORE.SALES_ORDER;
INSERT INTO ACME_EDP.CORE.SALES_ORDER
SELECT
    MD5(o.ORDER_BK), o.ORDER_BK, o.CUSTOMER_BK,
    -- Point-in-time join: attach the customer version that was current when the
    -- order was placed.  This is the whole reason CUSTOMER is SCD2.
    (SELECT c.CUSTOMER_SK FROM ACME_EDP.CORE.CUSTOMER c
      WHERE c.CUSTOMER_BK = o.CUSTOMER_BK
        AND CAST(o.ORDER_DATE AS TIMESTAMP) >= c.VALID_FROM
        AND CAST(o.ORDER_DATE AS TIMESTAMP) <  c.VALID_TO
      LIMIT 1)                                       AS CUSTOMER_SK,
    o.ORDER_DATE, o.ORDER_STATUS, o.CHANNEL, o.CURRENCY_CODE, o.ORDER_AMOUNT,
    o.DISCOUNT_AMOUNT, o.SHIPPING_AMOUNT, o.NET_AMOUNT,
    (o.ORDER_STATUS IN ('COMPLETED','SHIPPED'))      AS IS_REVENUE_RECOGNISED,
    o.SOURCE_CREATED_AT, o.SOURCE_UPDATED_AT, o._BATCH_ID, o._CORRELATION_ID,
    CURRENT_TIMESTAMP
FROM ACME_EDP.STAGING.STG_SALES_ORDER o
WHERE o.DQ_STATUS <> 'FAIL';

DELETE FROM ACME_EDP.CORE.SALES_ORDER_ITEM;
INSERT INTO ACME_EDP.CORE.SALES_ORDER_ITEM
SELECT MD5(ORDER_ITEM_BK), ORDER_ITEM_BK, ORDER_BK, PRODUCT_BK, SKU, QUANTITY,
       UNIT_PRICE, LINE_AMOUNT, CURRENCY_CODE, _BATCH_ID, CURRENT_TIMESTAMP
FROM ACME_EDP.STAGING.STG_SALES_ORDER_ITEM
WHERE DQ_STATUS <> 'FAIL'
  -- Referential integrity is enforced here, not by a constraint: an orphan line
  -- is reported by DQ-OI-003 and excluded from CORE rather than corrupting
  -- revenue aggregates.
  AND ORDER_BK IN (SELECT ORDER_BK FROM ACME_EDP.CORE.SALES_ORDER);

DELETE FROM ACME_EDP.CORE.SUPPORT_CASE;
INSERT INTO ACME_EDP.CORE.SUPPORT_CASE
SELECT
    MD5(CASE_BK), CASE_BK, CUSTOMER_BK, CASE_TYPE, PRIORITY, SUBJECT, DESCRIPTION,
    STATUS, CHANNEL, OPENED_AT, RESOLVED_AT, RESOLUTION_HOURS, RESOLUTION_NOTES,
    CSAT_SCORE, REOPEN_COUNT,
    -- SLA targets come from KB-010 (escalation policy) and are encoded once here.
    CASE PRIORITY
        WHEN 'CRITICAL' THEN COALESCE(RESOLUTION_HOURS, 999) > 2
        WHEN 'HIGH'     THEN COALESCE(RESOLUTION_HOURS, 999) > 8
        WHEN 'MEDIUM'   THEN COALESCE(RESOLUTION_HOURS, 999) > 24
        ELSE                 COALESCE(RESOLUTION_HOURS, 999) > 72
    END                                             AS IS_SLA_BREACHED,
    _BATCH_ID, CURRENT_TIMESTAMP
FROM ACME_EDP.STAGING.STG_SUPPORT_CASE
WHERE DQ_STATUS <> 'FAIL';

DELETE FROM ACME_EDP.CORE.CUSTOMER_INTERACTION;
INSERT INTO ACME_EDP.CORE.CUSTOMER_INTERACTION
SELECT MD5(INTERACTION_BK), INTERACTION_BK, CUSTOMER_BK, INTERACTION_TYPE, CHANNEL,
       INTERACTION_TS, CAMPAIGN_ID,
       (INTERACTION_TYPE IN ('CART_ABANDONED','NEWSLETTER_UNSUBSCRIBE')) AS IS_NEGATIVE_SIGNAL,
       _BATCH_ID, CURRENT_TIMESTAMP
FROM ACME_EDP.STAGING.STG_CUSTOMER_INTERACTION
WHERE DQ_STATUS <> 'FAIL';

DELETE FROM ACME_EDP.CORE.LOYALTY_ACCOUNT;
INSERT INTO ACME_EDP.CORE.LOYALTY_ACCOUNT
SELECT MD5(LOYALTY_ACCOUNT_BK), LOYALTY_ACCOUNT_BK, CUSTOMER_BK, TIER,
       CASE TIER WHEN 'PLATINUM' THEN 4 WHEN 'GOLD' THEN 3
                 WHEN 'SILVER' THEN 2 WHEN 'BRONZE' THEN 1 ELSE 0 END AS TIER_RANK,
       POINTS_BALANCE, POINTS_EARNED_LIFETIME, POINTS_REDEEMED_LIFETIME,
       ENROLLED_AT, LAST_ACTIVITY_AT, STATUS, _BATCH_ID, CURRENT_TIMESTAMP
FROM ACME_EDP.STAGING.STG_LOYALTY_ACCOUNT
WHERE DQ_STATUS <> 'FAIL';
