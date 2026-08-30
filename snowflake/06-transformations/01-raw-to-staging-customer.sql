-- =============================================================================
-- 06-01  RAW -> STAGING : CUSTOMER      [portable]
-- =============================================================================
-- What this step is responsible for:
--   * typing        - permissive VARCHAR becomes DATE / BOOLEAN / NUMBER, using
--                     TRY_CAST so a single bad value cannot fail the whole load
--   * standardising - trim, case-fold the e-mail, normalise the phone
--   * validating    - each row is stamped PASS / WARN / FAIL with the rule ids
--   * deduplicating - exact replays and fuzzy duplicates collapse to one row
--
-- Deduplication is two-stage on purpose:
--   Stage 1 (exact)  keep the latest version of each business key.  Source
--                    replays are common and are not a data quality problem.
--   Stage 2 (fuzzy)  group by MATCH_KEY (lower-cased e-mail, or name+postcode
--                    when the e-mail is missing) and elect a survivor: the
--                    oldest CREATED_AT wins, because the first record is the
--                    one other systems already reference.
-- Rows that fail a BLOCKING rule are NOT silently dropped - they are written to
-- RAW.RAW_REJECTED_RECORDS by 09-data-quality/03-quarantine-failed-records.sql.
-- =============================================================================

DELETE FROM ACME_EDP.STAGING.STG_CUSTOMER;

INSERT INTO ACME_EDP.STAGING.STG_CUSTOMER (
    CUSTOMER_BK, SOURCE_SYSTEM, FIRST_NAME, LAST_NAME, FULL_NAME, EMAIL, EMAIL_IS_VALID,
    PHONE, BIRTH_DATE, CUSTOMER_SEGMENT, MARKETING_OPT_IN, PREFERRED_CHANNEL, STATUS,
    SOURCE_CREATED_AT, SOURCE_UPDATED_AT, MATCH_KEY, DQ_STATUS, DQ_FAILED_RULES,
    _BATCH_ID, _CORRELATION_ID, _LOADED_AT, _ROW_HASH
)
WITH typed AS (
    SELECT
        TRIM(CUSTOMER_ID)                                     AS CUSTOMER_BK,
        COALESCE(SOURCE_SYSTEM, 'CRM')                        AS SOURCE_SYSTEM,
        TRIM(FIRST_NAME)                                      AS FIRST_NAME,
        TRIM(LAST_NAME)                                       AS LAST_NAME,
        LOWER(TRIM(EMAIL))                                    AS EMAIL,
        REGEXP_REPLACE(COALESCE(PHONE, ''), '[^0-9+]', '')    AS PHONE,
        TRY_CAST(BIRTH_DATE AS DATE)                          AS BIRTH_DATE,
        UPPER(TRIM(CUSTOMER_SEGMENT))                         AS CUSTOMER_SEGMENT,
        CASE WHEN LOWER(MARKETING_OPT_IN) IN ('true','1','y','yes') THEN TRUE
             WHEN LOWER(MARKETING_OPT_IN) IN ('false','0','n','no') THEN FALSE
             ELSE NULL END                                    AS MARKETING_OPT_IN,
        UPPER(TRIM(PREFERRED_CHANNEL))                        AS PREFERRED_CHANNEL,
        UPPER(TRIM(STATUS))                                   AS STATUS,
        TRY_CAST(CREATED_AT AS TIMESTAMP_NTZ)                 AS SOURCE_CREATED_AT,
        TRY_CAST(UPDATED_AT AS TIMESTAMP_NTZ)                 AS SOURCE_UPDATED_AT,
        _BATCH_ID, _CORRELATION_ID
    FROM ACME_EDP.RAW.RAW_CRM_CUSTOMER
),
validated AS (
    SELECT
        t.*,
        -- DQ-C-001 completeness: the business key must be present
        (CUSTOMER_BK IS NULL OR CUSTOMER_BK = '')                             AS FAIL_MISSING_KEY,
        -- DQ-C-002 validity: RFC-shaped e-mail with a real TLD
        NOT REGEXP_LIKE(COALESCE(EMAIL,''), '^[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}$')
                                                                              AS FAIL_EMAIL,
        -- DQ-C-003 validity: plausible date of birth
        (BIRTH_DATE IS NOT NULL
            AND (BIRTH_DATE > CURRENT_DATE OR BIRTH_DATE < DATE '1900-01-01')) AS FAIL_BIRTH_DATE,
        -- DQ-C-004 consistency: status from the controlled vocabulary
        (STATUS NOT IN ('ACTIVE','INACTIVE','CLOSED'))                        AS FAIL_STATUS
    FROM typed t
),
scored AS (
    SELECT
        v.*,
        CASE
            WHEN FAIL_MISSING_KEY THEN 'FAIL'
            WHEN FAIL_EMAIL OR FAIL_BIRTH_DATE OR FAIL_STATUS THEN 'WARN'
            ELSE 'PASS'
        END AS DQ_STATUS,
        TRIM(
            CASE WHEN FAIL_MISSING_KEY  THEN 'DQ-C-001 ' ELSE '' END ||
            CASE WHEN FAIL_EMAIL        THEN 'DQ-C-002 ' ELSE '' END ||
            CASE WHEN FAIL_BIRTH_DATE   THEN 'DQ-C-003 ' ELSE '' END ||
            CASE WHEN FAIL_STATUS       THEN 'DQ-C-004 ' ELSE '' END
        ) AS DQ_FAILED_RULES
    FROM validated v
),
-- Stage 1: collapse exact replays of the same business key.
deduped_exact AS (
    SELECT *
    FROM scored
    WHERE CUSTOMER_BK IS NOT NULL AND CUSTOMER_BK <> ''
    QUALIFY ROW_NUMBER() OVER (
        PARTITION BY CUSTOMER_BK
        ORDER BY SOURCE_UPDATED_AT DESC NULLS LAST, SOURCE_CREATED_AT DESC NULLS LAST
    ) = 1
),
-- Stage 2: fuzzy match key.  E-mail is the strongest available identifier; when
-- it is absent or malformed we fall back to a normalised name key rather than
-- creating a spurious singleton match group.
matched AS (
    SELECT
        d.*,
        MD5(
            CASE
                WHEN NOT FAIL_EMAIL AND EMAIL IS NOT NULL THEN EMAIL
                ELSE LOWER(COALESCE(FIRST_NAME,'') || '|' || COALESCE(LAST_NAME,'') || '|' ||
                           COALESCE(CAST(BIRTH_DATE AS VARCHAR),''))
            END
        ) AS MATCH_KEY
    FROM deduped_exact d
),
survivors AS (
    SELECT *
    FROM matched
    -- Survivorship: earliest created record wins the golden row; later
    -- duplicates are suppressed here and reported by DQ-C-005.
    QUALIFY ROW_NUMBER() OVER (
        PARTITION BY MATCH_KEY
        ORDER BY SOURCE_CREATED_AT ASC NULLS LAST, CUSTOMER_BK ASC
    ) = 1
)
SELECT
    CUSTOMER_BK,
    SOURCE_SYSTEM,
    FIRST_NAME,
    LAST_NAME,
    TRIM(COALESCE(FIRST_NAME,'') || ' ' || COALESCE(LAST_NAME,''))  AS FULL_NAME,
    EMAIL,
    NOT FAIL_EMAIL                                                   AS EMAIL_IS_VALID,
    PHONE,
    BIRTH_DATE,
    CUSTOMER_SEGMENT,
    MARKETING_OPT_IN,
    PREFERRED_CHANNEL,
    STATUS,
    SOURCE_CREATED_AT,
    SOURCE_UPDATED_AT,
    MATCH_KEY,
    DQ_STATUS,
    NULLIF(DQ_FAILED_RULES, '')                                      AS DQ_FAILED_RULES,
    _BATCH_ID,
    _CORRELATION_ID,
    CURRENT_TIMESTAMP                                                AS _LOADED_AT,
    -- Row hash over *tracked* attributes only.  Audit columns are excluded so
    -- that re-ingesting an unchanged record does not create an SCD2 version.
    MD5(COALESCE(FIRST_NAME,'') || '|' || COALESCE(LAST_NAME,'') || '|' ||
        COALESCE(EMAIL,'')      || '|' || COALESCE(PHONE,'')     || '|' ||
        COALESCE(CUSTOMER_SEGMENT,'') || '|' || COALESCE(STATUS,'') || '|' ||
        COALESCE(PREFERRED_CHANNEL,'') || '|' ||
        COALESCE(CAST(MARKETING_OPT_IN AS VARCHAR),''))              AS _ROW_HASH
FROM survivors;
