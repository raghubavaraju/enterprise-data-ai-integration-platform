-- =============================================================================
-- 10-01  Functional roles, service users and grants                [Snowflake only]
-- =============================================================================
-- Run as SECURITYADMIN, before 02-tables, because ownership matters: whichever
-- role creates an object owns it, and retro-fitting ownership across six schemas
-- is an afternoon nobody enjoys.
--
-- Two principles govern everything below.
--
--   1. Nobody reads a base table.  Every consumer - human or machine - is
--      granted on views.  A view is the only place a masking policy, a row
--      access policy and a column projection can all be enforced together, and
--      it is the only interface that survives a table being rebuilt.
--
--   2. Access roles are granted to functional roles; functional roles are
--      granted to users.  Never a privilege straight to a user.  The access
--      role layer makes "what can the AI service see?" answerable by
--      reading one object instead of auditing every grant in the account.
--
-- Least privilege here is not a slogan: ACME_AI_SERVICE can INSERT into exactly
-- three tables and SELECT from exactly two views.  If the generative service is
-- ever compromised, that list is the blast radius.
-- =============================================================================

USE ROLE SECURITYADMIN;

-- -----------------------------------------------------------------------------
-- Functional roles - what a person or service *is*
-- -----------------------------------------------------------------------------
CREATE ROLE IF NOT EXISTS ACME_DATA_ENGINEER
    COMMENT = 'Builds and operates the platform. Owns every pipeline object.';
CREATE ROLE IF NOT EXISTS ACME_DATA_STEWARD
    COMMENT = 'Governance. Reads everything unmasked; manages DQ rules; alters no data.';
CREATE ROLE IF NOT EXISTS ACME_ANALYST
    COMMENT = 'Reads CORE and ANALYTICS views. PII masked unless separately entitled.';
CREATE ROLE IF NOT EXISTS ACME_INTEGRATION_RO
    COMMENT = 'The MuleSoft system API. Read-only, views only, no RAW.';
CREATE ROLE IF NOT EXISTS ACME_AI_SERVICE
    COMMENT = 'The generative service. AI-safe views plus three AI write targets.';
CREATE ROLE IF NOT EXISTS ACME_PII_READER
    COMMENT = 'Entitlement role, not a job. Unmasks PII for the roles it is granted to.';

-- -----------------------------------------------------------------------------
-- Access roles - what may be *done* to a set of objects
--
-- Named <SCHEMA>_<VERB>.  The verb is the whole point: a reviewer scanning the
-- grant list can see that no role anywhere holds RAW_W except the engineer.
-- -----------------------------------------------------------------------------
CREATE ROLE IF NOT EXISTS ACME_AR_RAW_R;
CREATE ROLE IF NOT EXISTS ACME_AR_STAGING_R;
CREATE ROLE IF NOT EXISTS ACME_AR_CORE_R;
CREATE ROLE IF NOT EXISTS ACME_AR_ANALYTICS_R;
CREATE ROLE IF NOT EXISTS ACME_AR_AI_R;
CREATE ROLE IF NOT EXISTS ACME_AR_AI_W;
CREATE ROLE IF NOT EXISTS ACME_AR_GOVERNANCE_R;
CREATE ROLE IF NOT EXISTS ACME_AR_GOVERNANCE_W;

-- -----------------------------------------------------------------------------
-- Role hierarchy
--
-- Every functional role rolls up to SYSADMIN so that SYSADMIN can administer
-- what it does not own. Skipping this is the most common Snowflake RBAC defect:
-- objects become invisible to the role expected to manage them.
-- -----------------------------------------------------------------------------
GRANT ROLE ACME_DATA_ENGINEER   TO ROLE SYSADMIN;
GRANT ROLE ACME_DATA_STEWARD    TO ROLE SYSADMIN;
GRANT ROLE ACME_ANALYST         TO ROLE SYSADMIN;
GRANT ROLE ACME_INTEGRATION_RO  TO ROLE SYSADMIN;
GRANT ROLE ACME_AI_SERVICE      TO ROLE SYSADMIN;

GRANT ROLE ACME_AR_RAW_R        TO ROLE ACME_DATA_ENGINEER;
GRANT ROLE ACME_AR_STAGING_R    TO ROLE ACME_DATA_ENGINEER;
GRANT ROLE ACME_AR_CORE_R       TO ROLE ACME_DATA_ENGINEER;
GRANT ROLE ACME_AR_ANALYTICS_R  TO ROLE ACME_DATA_ENGINEER;
GRANT ROLE ACME_AR_AI_R         TO ROLE ACME_DATA_ENGINEER;
GRANT ROLE ACME_AR_AI_W         TO ROLE ACME_DATA_ENGINEER;
GRANT ROLE ACME_AR_GOVERNANCE_R TO ROLE ACME_DATA_ENGINEER;
GRANT ROLE ACME_AR_GOVERNANCE_W TO ROLE ACME_DATA_ENGINEER;

GRANT ROLE ACME_AR_CORE_R       TO ROLE ACME_ANALYST;
GRANT ROLE ACME_AR_ANALYTICS_R  TO ROLE ACME_ANALYST;
GRANT ROLE ACME_AR_GOVERNANCE_R TO ROLE ACME_ANALYST;

GRANT ROLE ACME_AR_CORE_R       TO ROLE ACME_DATA_STEWARD;
GRANT ROLE ACME_AR_ANALYTICS_R  TO ROLE ACME_DATA_STEWARD;
GRANT ROLE ACME_AR_AI_R         TO ROLE ACME_DATA_STEWARD;
GRANT ROLE ACME_AR_GOVERNANCE_R TO ROLE ACME_DATA_STEWARD;
GRANT ROLE ACME_AR_GOVERNANCE_W TO ROLE ACME_DATA_STEWARD;
GRANT ROLE ACME_PII_READER      TO ROLE ACME_DATA_STEWARD;

GRANT ROLE ACME_AR_ANALYTICS_R  TO ROLE ACME_INTEGRATION_RO;
GRANT ROLE ACME_AR_AI_R         TO ROLE ACME_INTEGRATION_RO;
GRANT ROLE ACME_AR_GOVERNANCE_R TO ROLE ACME_INTEGRATION_RO;

-- Deliberately NOT granted to ACME_AI_SERVICE: CORE_R, ANALYTICS_R, RAW_R.
-- The AI service reaches customer data only through the two AI-safe views,
-- which are constructed without direct identifiers rather than filtered.
GRANT ROLE ACME_AR_AI_R         TO ROLE ACME_AI_SERVICE;
GRANT ROLE ACME_AR_AI_W         TO ROLE ACME_AI_SERVICE;

-- -----------------------------------------------------------------------------
-- Warehouse grants.  Separate warehouses are a cost boundary and a blast-radius
-- boundary: a runaway generative loop suspends ACME_AI_WH and the service desk
-- keeps working.
-- -----------------------------------------------------------------------------
GRANT USAGE ON WAREHOUSE ACME_INTEGRATION_WH TO ROLE ACME_INTEGRATION_RO;
GRANT USAGE ON WAREHOUSE ACME_INTEGRATION_WH TO ROLE ACME_ANALYST;
GRANT USAGE ON WAREHOUSE ACME_TRANSFORM_WH   TO ROLE ACME_DATA_ENGINEER;
GRANT USAGE ON WAREHOUSE ACME_TRANSFORM_WH   TO ROLE ACME_DATA_STEWARD;
GRANT USAGE ON WAREHOUSE ACME_AI_WH          TO ROLE ACME_AI_SERVICE;
GRANT MONITOR ON WAREHOUSE ACME_AI_WH        TO ROLE ACME_DATA_STEWARD;

-- -----------------------------------------------------------------------------
-- Database and schema usage.  USAGE is not read access; it is the right to
-- resolve a name.  Without it a grant on an object is unusable.
-- -----------------------------------------------------------------------------
GRANT USAGE ON DATABASE ACME_EDP TO ROLE ACME_AR_RAW_R;
GRANT USAGE ON DATABASE ACME_EDP TO ROLE ACME_AR_STAGING_R;
GRANT USAGE ON DATABASE ACME_EDP TO ROLE ACME_AR_CORE_R;
GRANT USAGE ON DATABASE ACME_EDP TO ROLE ACME_AR_ANALYTICS_R;
GRANT USAGE ON DATABASE ACME_EDP TO ROLE ACME_AR_AI_R;
GRANT USAGE ON DATABASE ACME_EDP TO ROLE ACME_AR_AI_W;
GRANT USAGE ON DATABASE ACME_EDP TO ROLE ACME_AR_GOVERNANCE_R;
GRANT USAGE ON DATABASE ACME_EDP TO ROLE ACME_AR_GOVERNANCE_W;

GRANT USAGE ON SCHEMA ACME_EDP.RAW        TO ROLE ACME_AR_RAW_R;
GRANT USAGE ON SCHEMA ACME_EDP.STAGING    TO ROLE ACME_AR_STAGING_R;
GRANT USAGE ON SCHEMA ACME_EDP.CORE       TO ROLE ACME_AR_CORE_R;
GRANT USAGE ON SCHEMA ACME_EDP.ANALYTICS  TO ROLE ACME_AR_ANALYTICS_R;
GRANT USAGE ON SCHEMA ACME_EDP.AI         TO ROLE ACME_AR_AI_R;
GRANT USAGE ON SCHEMA ACME_EDP.AI         TO ROLE ACME_AR_AI_W;
GRANT USAGE ON SCHEMA ACME_EDP.GOVERNANCE TO ROLE ACME_AR_GOVERNANCE_R;
GRANT USAGE ON SCHEMA ACME_EDP.GOVERNANCE TO ROLE ACME_AR_GOVERNANCE_W;

-- -----------------------------------------------------------------------------
-- Object grants.
--
-- RAW and STAGING: base-table SELECT, engineer only.  These layers are
-- source-shaped and full of defects that have not yet been quarantined; an
-- analyst reading them draws a wrong conclusion in good faith.
-- -----------------------------------------------------------------------------
GRANT SELECT ON ALL TABLES    IN SCHEMA ACME_EDP.RAW     TO ROLE ACME_AR_RAW_R;
GRANT SELECT ON FUTURE TABLES IN SCHEMA ACME_EDP.RAW     TO ROLE ACME_AR_RAW_R;
GRANT SELECT ON ALL TABLES    IN SCHEMA ACME_EDP.STAGING TO ROLE ACME_AR_STAGING_R;
GRANT SELECT ON FUTURE TABLES IN SCHEMA ACME_EDP.STAGING TO ROLE ACME_AR_STAGING_R;

-- CORE and ANALYTICS: views only.  FUTURE VIEWS matters more than ALL VIEWS -
-- it is what stops the next view added by a deployment from being invisible
-- until somebody notices and issues a manual grant.
GRANT SELECT ON ALL VIEWS     IN SCHEMA ACME_EDP.CORE      TO ROLE ACME_AR_CORE_R;
GRANT SELECT ON FUTURE VIEWS  IN SCHEMA ACME_EDP.CORE      TO ROLE ACME_AR_CORE_R;
GRANT SELECT ON ALL VIEWS     IN SCHEMA ACME_EDP.ANALYTICS TO ROLE ACME_AR_ANALYTICS_R;
GRANT SELECT ON FUTURE VIEWS  IN SCHEMA ACME_EDP.ANALYTICS TO ROLE ACME_AR_ANALYTICS_R;

-- AI read: the two AI-safe views and the churn score, nothing else.  Note the
-- absence of a blanket FUTURE VIEWS grant on AI - a future view in this schema
-- might expose grounding text, so each one is an explicit decision.
GRANT SELECT ON VIEW  ACME_EDP.AI.V_CUSTOMER_AI_CONTEXT      TO ROLE ACME_AR_AI_R;
GRANT SELECT ON VIEW  ACME_EDP.AI.V_CUSTOMER_SUPPORT_CONTEXT TO ROLE ACME_AR_AI_R;
GRANT SELECT ON TABLE ACME_EDP.AI.CUSTOMER_CHURN_SCORE       TO ROLE ACME_AR_AI_R;
GRANT SELECT ON TABLE ACME_EDP.AI.KB_CHUNK                   TO ROLE ACME_AR_AI_R;
GRANT SELECT ON TABLE ACME_EDP.AI.KB_DOCUMENT                TO ROLE ACME_AR_AI_R;
GRANT SELECT ON TABLE ACME_EDP.AI.AI_CUSTOMER_INSIGHTS       TO ROLE ACME_AR_AI_R;

-- AI write: exactly three tables, INSERT only.  No UPDATE and no DELETE, because
-- generated content is an append-only record - an insight that was shown to an
-- agent must still be readable after it is superseded, or the audit trail is
-- fiction.
GRANT INSERT ON TABLE ACME_EDP.AI.AI_CUSTOMER_INSIGHTS TO ROLE ACME_AR_AI_W;
GRANT INSERT ON TABLE ACME_EDP.AI.AI_REQUEST_AUDIT     TO ROLE ACME_AR_AI_W;
GRANT INSERT ON TABLE ACME_EDP.AI.AI_EVALUATION_RESULT TO ROLE ACME_AR_AI_W;

-- Governance: readable by everyone who reads data, because a consumer who
-- cannot see the DQ scorecard cannot judge whether to trust the number.
GRANT SELECT ON ALL TABLES    IN SCHEMA ACME_EDP.GOVERNANCE TO ROLE ACME_AR_GOVERNANCE_R;
GRANT SELECT ON FUTURE TABLES IN SCHEMA ACME_EDP.GOVERNANCE TO ROLE ACME_AR_GOVERNANCE_R;
GRANT SELECT ON ALL VIEWS     IN SCHEMA ACME_EDP.GOVERNANCE TO ROLE ACME_AR_GOVERNANCE_R;
GRANT SELECT ON FUTURE VIEWS  IN SCHEMA ACME_EDP.GOVERNANCE TO ROLE ACME_AR_GOVERNANCE_R;

-- Stewards maintain the rule catalogue and the dictionary; they do not touch
-- results, which are evidence.
GRANT INSERT, UPDATE, DELETE ON TABLE ACME_EDP.GOVERNANCE.DQ_RULE         TO ROLE ACME_AR_GOVERNANCE_W;
GRANT INSERT, UPDATE, DELETE ON TABLE ACME_EDP.GOVERNANCE.DATA_DICTIONARY TO ROLE ACME_AR_GOVERNANCE_W;
GRANT INSERT, UPDATE, DELETE ON TABLE ACME_EDP.GOVERNANCE.LINEAGE_EDGE    TO ROLE ACME_AR_GOVERNANCE_W;

-- -----------------------------------------------------------------------------
-- Ownership.  The engineer role owns the pipeline layers so that a deployment
-- does not require SECURITYADMIN.  Ownership of AI content tables stays with
-- the engineer too: the AI service can insert, never drop.
-- -----------------------------------------------------------------------------
GRANT OWNERSHIP ON SCHEMA ACME_EDP.RAW       TO ROLE ACME_DATA_ENGINEER COPY CURRENT GRANTS;
GRANT OWNERSHIP ON SCHEMA ACME_EDP.STAGING   TO ROLE ACME_DATA_ENGINEER COPY CURRENT GRANTS;
GRANT OWNERSHIP ON SCHEMA ACME_EDP.CORE      TO ROLE ACME_DATA_ENGINEER COPY CURRENT GRANTS;
GRANT OWNERSHIP ON SCHEMA ACME_EDP.ANALYTICS TO ROLE ACME_DATA_ENGINEER COPY CURRENT GRANTS;
GRANT OWNERSHIP ON SCHEMA ACME_EDP.AI        TO ROLE ACME_DATA_ENGINEER COPY CURRENT GRANTS;

-- -----------------------------------------------------------------------------
-- Service users.
--
-- Key-pair authentication only.  No password is set here and none should be:
-- a service account with a password is a credential that can be phished,
-- shared and reused, and it cannot be rotated without a deployment.
--
-- The public key is registered by the deployment pipeline from the secrets
-- manager.  It is on purpose absent from this file - see
-- docs/security-architecture.md section 4 for the rotation procedure.
-- -----------------------------------------------------------------------------
USE ROLE USERADMIN;

CREATE USER IF NOT EXISTS SVC_MULE_INTEGRATION
    DEFAULT_ROLE      = ACME_INTEGRATION_RO
    DEFAULT_WAREHOUSE = ACME_INTEGRATION_WH
    TYPE              = SERVICE
    COMMENT           = 'MuleSoft Snowflake system API. Key-pair auth, registered by CI.';

CREATE USER IF NOT EXISTS SVC_AI_SERVICE
    DEFAULT_ROLE      = ACME_AI_SERVICE
    DEFAULT_WAREHOUSE = ACME_AI_WH
    TYPE              = SERVICE
    COMMENT           = 'Generative capability service. Key-pair auth, registered by CI.';

CREATE USER IF NOT EXISTS SVC_PIPELINE
    DEFAULT_ROLE      = ACME_DATA_ENGINEER
    DEFAULT_WAREHOUSE = ACME_TRANSFORM_WH
    TYPE              = SERVICE
    COMMENT           = 'Task DAG and Snowpipe owner.';

USE ROLE SECURITYADMIN;
GRANT ROLE ACME_INTEGRATION_RO TO USER SVC_MULE_INTEGRATION;
GRANT ROLE ACME_AI_SERVICE     TO USER SVC_AI_SERVICE;
GRANT ROLE ACME_DATA_ENGINEER  TO USER SVC_PIPELINE;

-- -----------------------------------------------------------------------------
-- Verification.  Run after deployment and after any grant change; the output is
-- the evidence an access review needs, and it is cheaper to produce than to
-- reconstruct from ACCOUNT_USAGE six months later.
-- -----------------------------------------------------------------------------
-- SHOW GRANTS TO ROLE ACME_AI_SERVICE;
-- SHOW GRANTS TO ROLE ACME_INTEGRATION_RO;
--
-- The assertion that matters most - no consumer role can read a base table in
-- CORE or ANALYTICS:
--
-- SELECT GRANTEE_NAME, TABLE_CATALOG, TABLE_SCHEMA, NAME, PRIVILEGE
--   FROM SNOWFLAKE.ACCOUNT_USAGE.GRANTS_TO_ROLES
--  WHERE GRANTED_ON = 'TABLE'
--    AND TABLE_SCHEMA IN ('CORE', 'ANALYTICS')
--    AND DELETED_ON IS NULL
--    AND GRANTEE_NAME NOT IN ('ACME_DATA_ENGINEER', 'ACME_AR_RAW_R', 'ACME_AR_STAGING_R');
-- Expected: zero rows.
