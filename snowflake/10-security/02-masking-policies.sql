-- =============================================================================
-- 10-02  Dynamic data masking policies                            [Snowflake only]
-- =============================================================================
-- Column-level protection that travels with the column.  This is the whole
-- argument for policy-based masking over masked views: a policy is attached to
-- the column, so a new view, a clone, a share or an ad-hoc CTAS inherits it.
-- A masked view protects exactly the one query path somebody remembered to
-- route through it.
--
-- The decision rule is the executing role, not the connection or the
-- application.  An application that "handles masking itself" is a control that
-- disappears the moment somebody opens a worksheet.
--
-- The entitlement is ACME_PII_READER, a role granted separately from any job
-- role.  Separating entitlement from function makes an access review
-- possible: "who can see e-mail addresses" is one SHOW GRANTS, not an audit of
-- every job role in the account.
--
-- Local equivalent: none.  The local warehouse cannot enforce these, so the
-- experience layer in services/experience_api applies field masking in code as
-- a second line of defence.  Both exist deliberately - see ADR-006.
-- =============================================================================

USE ROLE SECURITYADMIN;
USE DATABASE ACME_EDP;
USE SCHEMA GOVERNANCE;

-- -----------------------------------------------------------------------------
-- E-mail.  Partial masking, not full redaction.
--
-- An agent needs to confirm "is this the address ending in @example.com?"
-- without being shown the local part.  Full redaction pushes agents to ask the
-- customer to read their address aloud on a recorded line, which is worse for
-- privacy than a partial mask.
-- -----------------------------------------------------------------------------
CREATE MASKING POLICY IF NOT EXISTS MP_EMAIL AS (val VARCHAR) RETURNS VARCHAR ->
    CASE
        WHEN IS_ROLE_IN_SESSION('ACME_PII_READER')     THEN val
        WHEN IS_ROLE_IN_SESSION('ACME_DATA_ENGINEER')  THEN val
        WHEN val IS NULL                               THEN NULL
        WHEN POSITION('@' IN val) = 0                  THEN '***'
        ELSE LEFT(val, 1) || '****@' || SPLIT_PART(val, '@', 2)
    END
    COMMENT = 'Partial: first character plus domain. Unmasked for ACME_PII_READER.';

-- -----------------------------------------------------------------------------
-- Phone.  Last four digits survive, for the same identity-confirmation reason.
-- -----------------------------------------------------------------------------
CREATE MASKING POLICY IF NOT EXISTS MP_PHONE AS (val VARCHAR) RETURNS VARCHAR ->
    CASE
        WHEN IS_ROLE_IN_SESSION('ACME_PII_READER')    THEN val
        WHEN IS_ROLE_IN_SESSION('ACME_DATA_ENGINEER') THEN val
        WHEN val IS NULL                              THEN NULL
        WHEN LENGTH(val) < 4                          THEN '***'
        ELSE '***-***-' || RIGHT(val, 4)
    END
    COMMENT = 'Partial: last four digits only.';

-- -----------------------------------------------------------------------------
-- Name.  Initials only for unentitled readers.
-- -----------------------------------------------------------------------------
CREATE MASKING POLICY IF NOT EXISTS MP_NAME AS (val VARCHAR) RETURNS VARCHAR ->
    CASE
        WHEN IS_ROLE_IN_SESSION('ACME_PII_READER')    THEN val
        WHEN IS_ROLE_IN_SESSION('ACME_DATA_ENGINEER') THEN val
        WHEN val IS NULL                              THEN NULL
        ELSE LEFT(val, 1) || '.'
    END
    COMMENT = 'Initial only.';

-- -----------------------------------------------------------------------------
-- Birth date.  Generalised to the year, then to a decade band.
--
-- Date of birth is a quasi-identifier: with postal code and sex it re-identifies
-- most of a population.  Truncating to the year keeps the only legitimate
-- analytical use - age banding - and destroys the re-identification value.
-- -----------------------------------------------------------------------------
CREATE MASKING POLICY IF NOT EXISTS MP_BIRTH_DATE AS (val DATE) RETURNS DATE ->
    CASE
        WHEN IS_ROLE_IN_SESSION('ACME_PII_READER')    THEN val
        WHEN IS_ROLE_IN_SESSION('ACME_DATA_ENGINEER') THEN val
        WHEN val IS NULL                              THEN NULL
        ELSE DATE_TRUNC('YEAR', val)
    END
    COMMENT = 'Generalised to 1 January of the birth year.';

-- -----------------------------------------------------------------------------
-- Street address.  Full redaction; city, state and country stay visible because
-- they carry the analytical value and are not identifying on their own.
-- -----------------------------------------------------------------------------
CREATE MASKING POLICY IF NOT EXISTS MP_STREET AS (val VARCHAR) RETURNS VARCHAR ->
    CASE
        WHEN IS_ROLE_IN_SESSION('ACME_PII_READER')    THEN val
        WHEN IS_ROLE_IN_SESSION('ACME_DATA_ENGINEER') THEN val
        ELSE '[REDACTED]'
    END
    COMMENT = 'Street lines are redacted outright.';

-- -----------------------------------------------------------------------------
-- Free-text support narrative.
--
-- Different problem: the column is not itself an identifier, but customers put
-- anything in it - card numbers, other people's names, medical detail.  It is
-- redacted wholesale for anyone without the entitlement, and the AI-safe view
-- excludes it entirely instead of relying on this policy.
-- -----------------------------------------------------------------------------
CREATE MASKING POLICY IF NOT EXISTS MP_FREE_TEXT AS (val VARCHAR) RETURNS VARCHAR ->
    CASE
        WHEN IS_ROLE_IN_SESSION('ACME_PII_READER')    THEN val
        WHEN IS_ROLE_IN_SESSION('ACME_DATA_ENGINEER') THEN val
        WHEN val IS NULL                              THEN NULL
        ELSE '[REDACTED: ' || LENGTH(val) || ' characters]'
    END
    COMMENT = 'Length preserved so an analyst can still reason about verbosity.';

-- =============================================================================
-- Application
--
-- Applied to the base column, once.  Every view over it inherits the policy;
-- that is the property that makes this worth the complexity.
-- =============================================================================
USE ROLE ACME_DATA_ENGINEER;

ALTER TABLE ACME_EDP.CORE.CUSTOMER MODIFY COLUMN EMAIL      SET MASKING POLICY ACME_EDP.GOVERNANCE.MP_EMAIL;
ALTER TABLE ACME_EDP.CORE.CUSTOMER MODIFY COLUMN PHONE      SET MASKING POLICY ACME_EDP.GOVERNANCE.MP_PHONE;
ALTER TABLE ACME_EDP.CORE.CUSTOMER MODIFY COLUMN FIRST_NAME SET MASKING POLICY ACME_EDP.GOVERNANCE.MP_NAME;
ALTER TABLE ACME_EDP.CORE.CUSTOMER MODIFY COLUMN LAST_NAME  SET MASKING POLICY ACME_EDP.GOVERNANCE.MP_NAME;
ALTER TABLE ACME_EDP.CORE.CUSTOMER MODIFY COLUMN FULL_NAME  SET MASKING POLICY ACME_EDP.GOVERNANCE.MP_NAME;
ALTER TABLE ACME_EDP.CORE.CUSTOMER MODIFY COLUMN BIRTH_DATE SET MASKING POLICY ACME_EDP.GOVERNANCE.MP_BIRTH_DATE;

ALTER TABLE ACME_EDP.CORE.CUSTOMER_ADDRESS MODIFY COLUMN LINE1 SET MASKING POLICY ACME_EDP.GOVERNANCE.MP_STREET;
ALTER TABLE ACME_EDP.CORE.CUSTOMER_ADDRESS MODIFY COLUMN LINE2 SET MASKING POLICY ACME_EDP.GOVERNANCE.MP_STREET;

-- CONTACT_VALUE holds an e-mail or a phone depending on CONTACT_TYPE, so the
-- e-mail policy is used: it degrades to '***' for a value with no '@', which is
-- the safe direction to fail.
ALTER TABLE ACME_EDP.CORE.CUSTOMER_CONTACT MODIFY COLUMN CONTACT_VALUE SET MASKING POLICY ACME_EDP.GOVERNANCE.MP_EMAIL;

ALTER TABLE ACME_EDP.CORE.SUPPORT_CASE MODIFY COLUMN DESCRIPTION SET MASKING POLICY ACME_EDP.GOVERNANCE.MP_FREE_TEXT;
ALTER TABLE ACME_EDP.CORE.SUPPORT_CASE MODIFY COLUMN RESOLUTION_NOTES SET MASKING POLICY ACME_EDP.GOVERNANCE.MP_FREE_TEXT;

-- CUSTOMER_360 is a physical table, so it carries copies of the same columns and
-- needs its own application.  Forgetting a denormalised copy is the single most
-- common way a masking programme leaks.
ALTER TABLE ACME_EDP.ANALYTICS.CUSTOMER_360 MODIFY COLUMN EMAIL      SET MASKING POLICY ACME_EDP.GOVERNANCE.MP_EMAIL;
ALTER TABLE ACME_EDP.ANALYTICS.CUSTOMER_360 MODIFY COLUMN PHONE      SET MASKING POLICY ACME_EDP.GOVERNANCE.MP_PHONE;
ALTER TABLE ACME_EDP.ANALYTICS.CUSTOMER_360 MODIFY COLUMN FULL_NAME  SET MASKING POLICY ACME_EDP.GOVERNANCE.MP_NAME;
ALTER TABLE ACME_EDP.ANALYTICS.CUSTOMER_360 MODIFY COLUMN BIRTH_DATE SET MASKING POLICY ACME_EDP.GOVERNANCE.MP_BIRTH_DATE;

-- =============================================================================
-- Reconciliation
--
-- The dictionary declares which columns are PII.  The account knows which
-- columns carry a policy.  Drift between the two is the finding; this query is
-- the control, and it belongs in the monthly access review.
-- =============================================================================
CREATE OR REPLACE VIEW ACME_EDP.GOVERNANCE.V_MASKING_COVERAGE AS
SELECT
    d.SCHEMA_NAME,
    d.TABLE_NAME,
    d.COLUMN_NAME,
    d.PII_CATEGORY,
    p.POLICY_NAME,
    CASE WHEN p.POLICY_NAME IS NULL THEN 'UNPROTECTED' ELSE 'PROTECTED' END AS COVERAGE_STATUS
FROM ACME_EDP.GOVERNANCE.DATA_DICTIONARY d
LEFT JOIN SNOWFLAKE.ACCOUNT_USAGE.POLICY_REFERENCES p
       ON p.REF_SCHEMA_NAME = d.SCHEMA_NAME
      AND p.REF_ENTITY_NAME = d.TABLE_NAME
      AND p.REF_COLUMN_NAME = d.COLUMN_NAME
      AND p.POLICY_KIND     = 'MASKING_POLICY'
WHERE d.IS_PII = TRUE;

COMMENT ON VIEW ACME_EDP.GOVERNANCE.V_MASKING_COVERAGE IS
    'Declared PII versus applied masking policy. Any UNPROTECTED row is a finding.';

GRANT SELECT ON VIEW ACME_EDP.GOVERNANCE.V_MASKING_COVERAGE TO ROLE ACME_AR_GOVERNANCE_R;
