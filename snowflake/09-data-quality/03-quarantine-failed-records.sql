-- =============================================================================
-- 09-03  Quarantine records that fail blocking rules      [portable]
-- =============================================================================
-- Dead-lettering, applied to data rather than to messages.  The three properties
-- that make it useful are the same in both cases: the bad record is *kept*, the
-- reason is recorded, and reprocessing is possible once the source is fixed.
--
-- Note that missing-business-key rows never reach STAGING (they cannot be keyed,
-- so they cannot be deduplicated), which is why this script reads RAW for
-- DQ-C-001 and STAGING for the value rules.
-- =============================================================================

DELETE FROM ACME_EDP.RAW.RAW_REJECTED_RECORDS;

-- DQ-C-001: customer with no business key
INSERT INTO ACME_EDP.RAW.RAW_REJECTED_RECORDS
SELECT
    MD5('DQ-C-001' || COALESCE(EMAIL, _ROW_HASH))    AS REJECT_ID,
    'RAW.RAW_CRM_CUSTOMER', COALESCE(EMAIL, '(no key)'), 'DQ-C-001', 'BLOCKING',
    'Customer record has no business key and cannot be identified or deduplicated.',
    SRC_PAYLOAD, _BATCH_ID, _CORRELATION_ID, CURRENT_TIMESTAMP
FROM ACME_EDP.RAW.RAW_CRM_CUSTOMER
WHERE CUSTOMER_ID IS NULL OR TRIM(CUSTOMER_ID) = '';

-- DQ-O-002 / DQ-O-003: orders that cannot be trusted for revenue
INSERT INTO ACME_EDP.RAW.RAW_REJECTED_RECORDS
SELECT
    MD5('DQ-O-002' || o.ORDER_BK), 'STAGING.STG_SALES_ORDER', o.ORDER_BK, 'DQ-O-002', 'BLOCKING',
    'Order amount is null or negative: ' || COALESCE(CAST(o.ORDER_AMOUNT AS VARCHAR), 'NULL'),
    NULL, o._BATCH_ID, o._CORRELATION_ID, CURRENT_TIMESTAMP
FROM ACME_EDP.STAGING.STG_SALES_ORDER o
WHERE o.ORDER_AMOUNT IS NULL OR o.ORDER_AMOUNT < 0;

INSERT INTO ACME_EDP.RAW.RAW_REJECTED_RECORDS
SELECT
    MD5('DQ-O-003' || o.ORDER_BK), 'STAGING.STG_SALES_ORDER', o.ORDER_BK, 'DQ-O-003', 'BLOCKING',
    'Order date is in the future: ' || COALESCE(CAST(o.ORDER_DATE AS VARCHAR), 'NULL'),
    NULL, o._BATCH_ID, o._CORRELATION_ID, CURRENT_TIMESTAMP
FROM ACME_EDP.STAGING.STG_SALES_ORDER o
WHERE o.ORDER_DATE IS NULL OR o.ORDER_DATE > CURRENT_DATE;

-- DQ-C-005: suppressed fuzzy duplicates, kept for steward review.  These are
-- WARNING, not BLOCKING - the surviving golden record loaded normally.
INSERT INTO ACME_EDP.RAW.RAW_REJECTED_RECORDS
SELECT
    MD5('DQ-C-005' || r.CUSTOMER_ID), 'RAW.RAW_CRM_CUSTOMER', r.CUSTOMER_ID, 'DQ-C-005', 'WARNING',
    'Suppressed as a duplicate of an existing customer with the same e-mail.',
    r.SRC_PAYLOAD, r._BATCH_ID, r._CORRELATION_ID, CURRENT_TIMESTAMP
FROM ACME_EDP.RAW.RAW_CRM_CUSTOMER r
WHERE r.CUSTOMER_ID IS NOT NULL
  AND NOT EXISTS (SELECT 1 FROM ACME_EDP.STAGING.STG_CUSTOMER s
                   WHERE s.CUSTOMER_BK = r.CUSTOMER_ID);
