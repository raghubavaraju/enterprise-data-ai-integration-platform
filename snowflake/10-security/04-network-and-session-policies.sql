-- =============================================================================
-- 10-04  Network policy, session policy, tags and access auditing  [Snowflake only]
-- =============================================================================
-- Perimeter and session controls, plus the classification tags that make an
-- access review answerable.
--
-- The ordering below is deliberate.  A network policy applied before the
-- allow-list is verified locks the account's own administrators out, and the
-- recovery path is a support ticket.  Apply at account level only after
-- confirming the policy on a test user.
-- =============================================================================

USE ROLE SECURITYADMIN;
USE DATABASE ACME_EDP;
USE SCHEMA GOVERNANCE;

-- -----------------------------------------------------------------------------
-- Network policy
--
-- The ranges below are placeholders.  They are substituted by the deployment
-- pipeline from the network configuration; committing real egress ranges to a
-- public repository would be a finding in itself.
--
-- Why a blocked list as well as an allowed list: allow-lists are maintained by
-- addition and rarely by subtraction, so a range that was decommissioned stays
-- allowed for years.  The blocked list is where a revoked range goes
-- immediately, and it wins over the allowed list.
-- -----------------------------------------------------------------------------
CREATE NETWORK POLICY IF NOT EXISTS NP_ACME_PLATFORM
    ALLOWED_IP_LIST = (
        '203.0.113.0/24',    -- placeholder: CloudHub VPC egress, production
        '198.51.100.0/24',   -- placeholder: CloudHub VPC egress, non-production
        '192.0.2.0/24'       -- placeholder: corporate VPN
    )
    BLOCKED_IP_LIST = ()
    COMMENT = 'Placeholder ranges (RFC 5737 documentation blocks). Substituted at deploy time.';

-- Applied to the service users first, and only then to the account.  A service
-- user has one known source; a human has a laptop and a home connection, and
-- discovering that at the account level is expensive.
ALTER USER SVC_MULE_INTEGRATION SET NETWORK_POLICY = NP_ACME_PLATFORM;
ALTER USER SVC_AI_SERVICE       SET NETWORK_POLICY = NP_ACME_PLATFORM;
ALTER USER SVC_PIPELINE         SET NETWORK_POLICY = NP_ACME_PLATFORM;

-- Account-level application, commented out on purpose.  Enable it only after
-- the per-user application has run clean for a full business cycle.
-- ALTER ACCOUNT SET NETWORK_POLICY = NP_ACME_PLATFORM;

-- -----------------------------------------------------------------------------
-- Session policy.  Short idle timeout for human sessions; the service users are
-- exempt because they hold no interactive session and a forced re-auth mid-batch
-- is an outage, not a control.
-- -----------------------------------------------------------------------------
CREATE SESSION POLICY IF NOT EXISTS SP_ACME_HUMAN
    SESSION_IDLE_TIMEOUT_MINS = 30
    SESSION_UI_IDLE_TIMEOUT_MINS = 30
    COMMENT = 'Human interactive sessions. Service users are not subject to this.';

-- ALTER ACCOUNT SET SESSION_POLICY = ACME_EDP.GOVERNANCE.SP_ACME_HUMAN;

-- -----------------------------------------------------------------------------
-- Authentication policy.  Key-pair only for service users; MFA for humans.
--
-- This is the control that makes the "no passwords for service accounts" claim
-- in the security documentation enforceable and not aspirational.
-- -----------------------------------------------------------------------------
CREATE AUTHENTICATION POLICY IF NOT EXISTS AP_SERVICE_KEYPAIR_ONLY
    AUTHENTICATION_METHODS = ('KEYPAIR')
    COMMENT = 'Service users authenticate with a key pair or not at all.';

ALTER USER SVC_MULE_INTEGRATION SET AUTHENTICATION POLICY AP_SERVICE_KEYPAIR_ONLY;
ALTER USER SVC_AI_SERVICE       SET AUTHENTICATION POLICY AP_SERVICE_KEYPAIR_ONLY;
ALTER USER SVC_PIPELINE         SET AUTHENTICATION POLICY AP_SERVICE_KEYPAIR_ONLY;

-- -----------------------------------------------------------------------------
-- Object tagging for classification.
--
-- Tags are what turn "is this column confidential?" from an opinion into a
-- queryable fact.  They also let a masking policy be attached by tag rather than
-- by column, which is how a large estate keeps coverage from drifting - the
-- alternative is remembering to ALTER every new table.
-- -----------------------------------------------------------------------------
USE ROLE ACME_DATA_ENGINEER;

CREATE TAG IF NOT EXISTS ACME_EDP.GOVERNANCE.CLASSIFICATION
    ALLOWED_VALUES 'PUBLIC', 'INTERNAL', 'CONFIDENTIAL', 'RESTRICTED'
    COMMENT = 'Data classification. Mirrors DATA_DICTIONARY.CLASSIFICATION.';

CREATE TAG IF NOT EXISTS ACME_EDP.GOVERNANCE.PII_CATEGORY
    ALLOWED_VALUES 'DIRECT_IDENTIFIER', 'QUASI_IDENTIFIER', 'NONE'
    COMMENT = 'PII category. Drives the tag-based masking assignment below.';

CREATE TAG IF NOT EXISTS ACME_EDP.GOVERNANCE.DATA_DOMAIN
    ALLOWED_VALUES 'CUSTOMER', 'ORDER', 'SUPPORT', 'LOYALTY', 'PRODUCT', 'GOVERNANCE', 'AI'
    COMMENT = 'Owning domain. Answers "who approves access to this?" without a meeting.';

ALTER TABLE ACME_EDP.CORE.CUSTOMER      SET TAG ACME_EDP.GOVERNANCE.DATA_DOMAIN = 'CUSTOMER';
ALTER TABLE ACME_EDP.CORE.SALES_ORDER   SET TAG ACME_EDP.GOVERNANCE.DATA_DOMAIN = 'ORDER';
ALTER TABLE ACME_EDP.CORE.SUPPORT_CASE  SET TAG ACME_EDP.GOVERNANCE.DATA_DOMAIN = 'SUPPORT';

ALTER TABLE ACME_EDP.CORE.CUSTOMER MODIFY COLUMN EMAIL
    SET TAG ACME_EDP.GOVERNANCE.PII_CATEGORY = 'DIRECT_IDENTIFIER',
        ACME_EDP.GOVERNANCE.CLASSIFICATION = 'RESTRICTED';
ALTER TABLE ACME_EDP.CORE.CUSTOMER MODIFY COLUMN PHONE
    SET TAG ACME_EDP.GOVERNANCE.PII_CATEGORY = 'DIRECT_IDENTIFIER',
        ACME_EDP.GOVERNANCE.CLASSIFICATION = 'RESTRICTED';
ALTER TABLE ACME_EDP.CORE.CUSTOMER MODIFY COLUMN BIRTH_DATE
    SET TAG ACME_EDP.GOVERNANCE.PII_CATEGORY = 'QUASI_IDENTIFIER',
        ACME_EDP.GOVERNANCE.CLASSIFICATION = 'CONFIDENTIAL';

-- Tag-based masking: any column anywhere in the account tagged as a direct
-- identifier is masked, including one added next quarter by somebody who never
-- read this file.  That property is the entire reason to prefer tags.
--
-- Enabled after the per-column assignments in 10-02 are verified, to avoid two
-- policies competing for the same column.
-- ALTER TAG ACME_EDP.GOVERNANCE.PII_CATEGORY
--     SET MASKING POLICY ACME_EDP.GOVERNANCE.MP_EMAIL;

-- -----------------------------------------------------------------------------
-- Access auditing
--
-- ACCESS_HISTORY records the columns a query actually touched, which is the only
-- reliable answer to "who read this customer's e-mail address".  Reconstructing
-- that from query text is guesswork the moment a view is involved.
--
-- Latency is up to three hours, so this is a detective control, not a preventive
-- one. It is paired with the preventive controls above, never substituted for
-- them.
-- -----------------------------------------------------------------------------
CREATE OR REPLACE VIEW ACME_EDP.GOVERNANCE.V_PII_ACCESS_AUDIT AS
SELECT
    ah.QUERY_START_TIME,
    ah.USER_NAME,
    qh.ROLE_NAME,
    qh.QUERY_TAG,                       -- carries the correlation id set by the API layer
    bcr.value:objectName::VARCHAR   AS OBJECT_NAME,
    col.value:columnName::VARCHAR   AS COLUMN_NAME,
    qh.WAREHOUSE_NAME,
    qh.QUERY_ID
FROM SNOWFLAKE.ACCOUNT_USAGE.ACCESS_HISTORY ah
JOIN SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY  qh
  ON qh.QUERY_ID = ah.QUERY_ID,
     LATERAL FLATTEN(input => ah.BASE_OBJECTS_ACCESSED) bcr,
     LATERAL FLATTEN(input => bcr.value:columns)        col
WHERE bcr.value:objectName::VARCHAR ILIKE 'ACME_EDP.CORE.CUSTOMER%'
  AND col.value:columnName::VARCHAR IN ('EMAIL', 'PHONE', 'BIRTH_DATE', 'FULL_NAME')
  AND ah.QUERY_START_TIME >= DATEADD('day', -90, CURRENT_TIMESTAMP());

COMMENT ON VIEW ACME_EDP.GOVERNANCE.V_PII_ACCESS_AUDIT IS
    'Every read of a direct identifier in the last 90 days, joined to the role and correlation id.';

USE ROLE SECURITYADMIN;
GRANT SELECT ON VIEW ACME_EDP.GOVERNANCE.V_PII_ACCESS_AUDIT TO ROLE ACME_DATA_STEWARD;

-- -----------------------------------------------------------------------------
-- Standing access-review queries.  Kept here so the review is a script somebody
-- runs, not a description somebody interprets.
--
-- 1. Roles that can read a direct identifier unmasked:
--      SHOW GRANTS OF ROLE ACME_PII_READER;
--
-- 2. Service users whose key has not been rotated in 90 days:
--      SELECT NAME, HAS_RSA_PUBLIC_KEY, LAST_SUCCESS_LOGIN
--        FROM SNOWFLAKE.ACCOUNT_USAGE.USERS
--       WHERE DELETED_ON IS NULL AND NAME LIKE 'SVC_%';
--
-- 3. Any object in CORE or ANALYTICS with no masking policy on a PII column:
--      SELECT * FROM ACME_EDP.GOVERNANCE.V_MASKING_COVERAGE
--       WHERE COVERAGE_STATUS = 'UNPROTECTED';
--
-- 4. Logins from outside the network policy (should be zero once enforced):
--      SELECT USER_NAME, CLIENT_IP, COUNT(*)
--        FROM SNOWFLAKE.ACCOUNT_USAGE.LOGIN_HISTORY
--       WHERE IS_SUCCESS = 'YES'
--         AND EVENT_TIMESTAMP >= DATEADD('day', -30, CURRENT_TIMESTAMP())
--       GROUP BY 1, 2;
-- -----------------------------------------------------------------------------
