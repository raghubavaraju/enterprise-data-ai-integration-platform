-- =============================================================================
-- 10-03  Row access policies                                      [Snowflake only]
-- =============================================================================
-- Masking answers "which columns may this role see".  Row access answers "which
-- rows".  They are different questions and a platform that only answers the
-- first will happily show an EU analyst the full masked list of US customers -
-- which is still a cross-border transfer.
--
-- Two policies here:
--
--   * regional segregation on CUSTOMER_360, driven by an entitlement table
--     and not by role names.  Encoding regions into role names means a new
--     region is a schema change; a mapping table makes it a row.
--
--   * consent-scoped access on the marketing consumption path, so a
--     marketing-purpose reader never sees a customer who opted out.  Purpose
--     limitation enforced in the platform is worth more than purpose limitation
--     promised in a policy document.
--
-- Performance note, because it is the usual objection: a row access policy is
-- inlined into the query plan, so the mapping-table lookup must be cheap and
-- must not correlate on a wide column.  ROLE_REGION_ENTITLEMENT is small enough
-- to be a broadcast join, and the predicate is on PRIMARY_COUNTRY, which is
-- part of the clustering key on CUSTOMER_360.
-- =============================================================================

USE ROLE ACME_DATA_ENGINEER;
USE DATABASE ACME_EDP;
USE SCHEMA GOVERNANCE;

-- -----------------------------------------------------------------------------
-- Entitlement mapping.  Stewards maintain it; it is the audit artefact for
-- "who could see EU customers on 3 March".
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ACME_EDP.GOVERNANCE.ROLE_REGION_ENTITLEMENT (
    ROLE_NAME       VARCHAR(128) NOT NULL,
    COUNTRY_CODE    VARCHAR(8)   NOT NULL,   -- ISO 3166-1 alpha-2, or '*' for all
    GRANTED_BY      VARCHAR(128),
    GRANTED_AT      TIMESTAMP_NTZ,
    JUSTIFICATION   VARCHAR(500),
    CONSTRAINT PK_ROLE_REGION_ENTITLEMENT PRIMARY KEY (ROLE_NAME, COUNTRY_CODE)
);

-- Seed. '*' is the platform-operations escape hatch and is on purpose narrow:
-- three roles, each of which is already able to read everything by other means.
INSERT INTO ACME_EDP.GOVERNANCE.ROLE_REGION_ENTITLEMENT
    (ROLE_NAME, COUNTRY_CODE, GRANTED_BY, GRANTED_AT, JUSTIFICATION)
SELECT column1, column2, column3, CURRENT_TIMESTAMP(), column4
FROM VALUES
    ('ACME_DATA_ENGINEER',  '*',  'PLATFORM_OWNER', 'Operates the pipeline; cannot debug what it cannot see.'),
    ('ACME_DATA_STEWARD',   '*',  'PLATFORM_OWNER', 'Governance function; stewardship is account-wide.'),
    ('ACME_INTEGRATION_RO', '*',  'PLATFORM_OWNER', 'Serves the service desk, which is staffed regionally at the API layer.'),
    ('ACME_ANALYST',        'US', 'DATA_PROTECTION', 'Default analyst entitlement is the home region only.'),
    ('ACME_ANALYST',        'CA', 'DATA_PROTECTION', 'North America reporting.')
WHERE NOT EXISTS (SELECT 1 FROM ACME_EDP.GOVERNANCE.ROLE_REGION_ENTITLEMENT);

-- -----------------------------------------------------------------------------
-- Regional row access policy.
--
-- CURRENT_ROLE() is not enough on its own - a user may activate a secondary
-- role - so IS_ROLE_IN_SESSION is used via an EXISTS over the mapping.  The
-- policy is written to fail closed: a role with no row in the mapping sees
-- nothing.
-- -----------------------------------------------------------------------------
CREATE ROW ACCESS POLICY IF NOT EXISTS RAP_CUSTOMER_REGION
    AS (country_code VARCHAR) RETURNS BOOLEAN ->
    EXISTS (
        SELECT 1
          FROM ACME_EDP.GOVERNANCE.ROLE_REGION_ENTITLEMENT e
         WHERE IS_ROLE_IN_SESSION(e.ROLE_NAME)
           AND (e.COUNTRY_CODE = '*' OR e.COUNTRY_CODE = country_code)
    )
    COMMENT = 'Regional segregation. Fails closed: an unmapped role sees no rows.';

ALTER TABLE ACME_EDP.ANALYTICS.CUSTOMER_360
    ADD ROW ACCESS POLICY ACME_EDP.GOVERNANCE.RAP_CUSTOMER_REGION ON (PRIMARY_COUNTRY);

-- -----------------------------------------------------------------------------
-- Consent-scoped policy for the marketing purpose.
--
-- Applied to the marketing view and not to CUSTOMER_360, because the same
-- customer must remain visible to the service desk after opting out of
-- marketing.  Consent limits a *purpose*, not existence - conflating the two is
-- how "we deleted them from everything" becomes an incident when the customer
-- calls support.
-- -----------------------------------------------------------------------------
CREATE ROW ACCESS POLICY IF NOT EXISTS RAP_MARKETING_CONSENT
    AS (marketing_opt_in BOOLEAN) RETURNS BOOLEAN ->
    CASE
        WHEN IS_ROLE_IN_SESSION('ACME_DATA_ENGINEER') THEN TRUE
        WHEN IS_ROLE_IN_SESSION('ACME_DATA_STEWARD')  THEN TRUE
        ELSE COALESCE(marketing_opt_in, FALSE)
    END
    COMMENT = 'Opted-out customers are invisible to the marketing consumption path. NULL is treated as no consent.';

-- The marketing view is created here instead of in 03-views because it exists
-- only to carry this policy; a view whose sole purpose is a control belongs
-- with the control.
CREATE OR REPLACE VIEW ACME_EDP.ANALYTICS.V_CUSTOMER_MARKETING AS
SELECT
    CUSTOMER_BK,
    CUSTOMER_SEGMENT,
    PREFERRED_CHANNEL,
    MARKETING_OPT_IN,
    PRIMARY_CITY,
    PRIMARY_STATE,
    PRIMARY_COUNTRY,
    VALUE_TIER,
    LOYALTY_TIER,
    ENGAGEMENT_SCORE,
    DAYS_SINCE_LAST_ORDER,
    AS_OF_TIMESTAMP
FROM ACME_EDP.ANALYTICS.CUSTOMER_360;

ALTER VIEW ACME_EDP.ANALYTICS.V_CUSTOMER_MARKETING
    ADD ROW ACCESS POLICY ACME_EDP.GOVERNANCE.RAP_MARKETING_CONSENT ON (MARKETING_OPT_IN);

COMMENT ON VIEW ACME_EDP.ANALYTICS.V_CUSTOMER_MARKETING IS
    'Marketing consumption path. No direct identifiers; consent enforced by row access policy.';

-- -----------------------------------------------------------------------------
-- Verification.  Run as each role after deployment.  The expected results are
-- part of the control, not an afterthought:
--
--   ACME_ANALYST      : sees US and CA rows only
--   ACME_DATA_STEWARD : sees every row
--   a role with no entitlement row : sees zero rows
--
-- USE ROLE ACME_ANALYST;
-- SELECT PRIMARY_COUNTRY, COUNT(*) FROM ACME_EDP.ANALYTICS.CUSTOMER_360 GROUP BY 1;
--
-- And the control that catches the policy being dropped in a hurry:
-- SELECT REF_ENTITY_NAME, POLICY_NAME
--   FROM SNOWFLAKE.ACCOUNT_USAGE.POLICY_REFERENCES
--  WHERE POLICY_KIND = 'ROW_ACCESS_POLICY';
-- Expected: CUSTOMER_360 and V_CUSTOMER_MARKETING both present.
-- -----------------------------------------------------------------------------
GRANT SELECT ON VIEW ACME_EDP.ANALYTICS.V_CUSTOMER_MARKETING TO ROLE ACME_AR_ANALYTICS_R;
