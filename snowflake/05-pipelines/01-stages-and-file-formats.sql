-- =============================================================================
-- 05-01  External stages and file formats      [Snowflake only]
-- =============================================================================
-- The landing contract between the source systems and this platform.
--
-- Two decisions worth defending:
--
--   ON_ERROR = 'CONTINUE' rather than 'ABORT_STATEMENT'. A single malformed
--   row must not reject a night's extract. The rejected rows are recoverable
--   from the load history and are surfaced by the data quality rules; aborting
--   would trade a reportable defect for an outage.
--
--   MATCH_BY_COLUMN_NAME = 'CASE_INSENSITIVE'. A source adding a column is a
--   normal event, not a breaking one - the new column lands in the untyped
--   payload and can be promoted to a typed column later, retrospectively. This
--   is what makes schema evolution survivable rather than a coordinated release.
-- =============================================================================

USE DATABASE ACME_EDP;
USE SCHEMA RAW;

CREATE FILE FORMAT IF NOT EXISTS FF_JSON
    TYPE = 'JSON'
    STRIP_OUTER_ARRAY = TRUE
    DATE_FORMAT = 'AUTO'
    TIMESTAMP_FORMAT = 'AUTO'
    COMPRESSION = 'AUTO'
    COMMENT = 'Source extracts delivered as JSON arrays.';

CREATE FILE FORMAT IF NOT EXISTS FF_CSV
    TYPE = 'CSV'
    FIELD_DELIMITER = ','
    SKIP_HEADER = 1
    FIELD_OPTIONALLY_ENCLOSED_BY = '"'
    NULL_IF = ('', 'NULL', 'null', '\\N')
    EMPTY_FIELD_AS_NULL = TRUE
    TRIM_SPACE = TRUE
    ERROR_ON_COLUMN_COUNT_MISMATCH = FALSE  -- see the schema-evolution note above
    COMMENT = 'Legacy extracts delivered as delimited files.';

-- Storage integration holds the cloud credential; the stage never does. This is
-- what keeps a cloud key out of every stage definition and out of any DDL a
-- developer can read.
CREATE STORAGE INTEGRATION IF NOT EXISTS ACME_LANDING_INTEGRATION
    TYPE = EXTERNAL_STAGE
    STORAGE_PROVIDER = 'S3'
    ENABLED = TRUE
    STORAGE_AWS_ROLE_ARN = '${landing.roleArn}'
    STORAGE_ALLOWED_LOCATIONS = ('s3://acme-edp-landing/');

CREATE STAGE IF NOT EXISTS STG_CRM
    STORAGE_INTEGRATION = ACME_LANDING_INTEGRATION
    URL = 's3://acme-edp-landing/crm/'
    FILE_FORMAT = FF_JSON
    DIRECTORY = (ENABLE = TRUE)
    COMMENT = 'CRM extracts. Versioned bucket; 90-day retention is the replay window.';

CREATE STAGE IF NOT EXISTS STG_OMS
    STORAGE_INTEGRATION = ACME_LANDING_INTEGRATION
    URL = 's3://acme-edp-landing/oms/'
    FILE_FORMAT = FF_JSON
    DIRECTORY = (ENABLE = TRUE);

CREATE STAGE IF NOT EXISTS STG_SUPPORT
    STORAGE_INTEGRATION = ACME_LANDING_INTEGRATION
    URL = 's3://acme-edp-landing/support/'
    FILE_FORMAT = FF_JSON
    DIRECTORY = (ENABLE = TRUE);

CREATE STAGE IF NOT EXISTS STG_LOYALTY
    STORAGE_INTEGRATION = ACME_LANDING_INTEGRATION
    URL = 's3://acme-edp-landing/loyalty/'
    FILE_FORMAT = FF_JSON
    DIRECTORY = (ENABLE = TRUE);

CREATE STAGE IF NOT EXISTS STG_PIM
    STORAGE_INTEGRATION = ACME_LANDING_INTEGRATION
    URL = 's3://acme-edp-landing/pim/'
    FILE_FORMAT = FF_CSV
    DIRECTORY = (ENABLE = TRUE);
