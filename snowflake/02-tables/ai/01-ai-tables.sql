-- =============================================================================
-- 02-AI  Feature store, scores, generated content, audit and evaluation
-- =============================================================================
-- The AI schema is separate from ANALYTICS on purpose (ADR-004):
--   * different retention (generated content is retained for audit, features
--     are cheap to recompute and are not),
--   * different access control (AI_INSIGHT_READER never sees raw PII),
--   * different cost centre (Cortex consumption is attributable to this schema),
--   * and generated content must never be mistaken for a system of record.
-- Every generated row therefore carries its model, prompt version, grounding
-- set, confidence and review status.
-- =============================================================================


-- Point-in-time feature store.  FEATURE_DATE makes training/serving skew
-- visible: a score is always explainable against the features as they were.
CREATE TABLE IF NOT EXISTS ACME_EDP.AI.CUSTOMER_FEATURES (
    CUSTOMER_BK              VARCHAR(64) NOT NULL,
    FEATURE_DATE             DATE        NOT NULL,
    -- recency / frequency / monetary
    F_RECENCY_DAYS           NUMBER(9,0),
    F_FREQUENCY_365D         NUMBER(12,0),
    F_MONETARY_365D          NUMBER(18,2),
    F_AVG_ORDER_VALUE        NUMBER(18,2),
    F_TENURE_DAYS            NUMBER(9,0),
    -- trend
    F_ORDER_TREND_RATIO      NUMBER(9,4),   -- 90d rate vs prior 275d rate
    F_REVENUE_TREND_RATIO    NUMBER(9,4),
    -- service
    F_CASES_90D              NUMBER(12,0),
    F_OPEN_CASES             NUMBER(12,0),
    F_AVG_CSAT               NUMBER(5,2),
    F_REOPEN_COUNT           NUMBER(12,0),
    F_SLA_BREACHES           NUMBER(12,0),
    -- loyalty / engagement
    F_LOYALTY_TIER_RANK      NUMBER(2,0),
    F_LOYALTY_INACTIVE_DAYS  NUMBER(9,0),
    F_ENGAGEMENT_SCORE       NUMBER(5,2),
    F_NEGATIVE_SIGNALS_90D   NUMBER(12,0),
    F_RETURN_RATE            NUMBER(9,4),
    -- bookkeeping
    FEATURE_SET_VERSION      VARCHAR(16),
    _BATCH_ID                VARCHAR(64),
    _LOADED_AT               TIMESTAMP_NTZ,
    CONSTRAINT PK_CUSTOMER_FEATURES PRIMARY KEY (CUSTOMER_BK, FEATURE_DATE)
);

CREATE TABLE IF NOT EXISTS ACME_EDP.AI.CUSTOMER_CHURN_SCORE (
    CUSTOMER_BK              VARCHAR(64) NOT NULL,
    SCORE_DATE               DATE        NOT NULL,
    CHURN_PROBABILITY        NUMBER(5,4),        -- 0.0000 - 1.0000
    CHURN_RISK_BAND          VARCHAR(16),        -- LOW | MEDIUM | HIGH | CRITICAL
    MODEL_NAME               VARCHAR(128),
    MODEL_VERSION            VARCHAR(32),
    SCORING_METHOD           VARCHAR(32),        -- RULE_BASED | ML | ENSEMBLE
    TOP_DRIVER_1             VARCHAR(128),
    TOP_DRIVER_1_CONTRIB     NUMBER(6,4),
    TOP_DRIVER_2             VARCHAR(128),
    TOP_DRIVER_2_CONTRIB     NUMBER(6,4),
    TOP_DRIVER_3             VARCHAR(128),
    TOP_DRIVER_3_CONTRIB     NUMBER(6,4),
    FEATURE_SET_VERSION      VARCHAR(16),
    _BATCH_ID                VARCHAR(64),
    _CORRELATION_ID          VARCHAR(64),
    _LOADED_AT               TIMESTAMP_NTZ,
    CONSTRAINT PK_CUSTOMER_CHURN_SCORE PRIMARY KEY (CUSTOMER_BK, SCORE_DATE)
) COMMENT = 'Churn scores. Deterministic and reproducible: the drivers are '
            'stored so the explanation is auditable, not regenerated on read.';

CREATE TABLE IF NOT EXISTS ACME_EDP.AI.AI_CUSTOMER_INSIGHTS (
    INSIGHT_ID               VARCHAR(64) NOT NULL,
    CUSTOMER_BK              VARCHAR(64) NOT NULL,
    INSIGHT_TYPE             VARCHAR(64) NOT NULL,   -- SUMMARY | CHURN_EXPLANATION |
                                                     -- NEXT_BEST_ACTION | SENTIMENT
    GENERATED_TEXT           VARCHAR(16777216),
    RECOMMENDED_ACTION       VARCHAR(500),
    ACTION_PRIORITY          VARCHAR(16),
    SENTIMENT_LABEL          VARCHAR(16),            -- POSITIVE | NEUTRAL | NEGATIVE
    SENTIMENT_SCORE          NUMBER(5,4),
    -- grounding and provenance: an insight without these is not auditable
    GROUNDING_SNAPSHOT       VARIANT,                -- exact facts given to the model
    GROUNDING_SOURCE_IDS     VARCHAR(2000),          -- KB article / case ids cited
    PROMPT_TEMPLATE_ID       VARCHAR(64),
    PROMPT_VERSION           VARCHAR(16),
    MODEL_PROVIDER           VARCHAR(32),
    MODEL_NAME               VARCHAR(128),
    MODEL_TEMPERATURE        NUMBER(4,2),
    INPUT_TOKENS             NUMBER(12,0),
    OUTPUT_TOKENS            NUMBER(12,0),
    LATENCY_MS               NUMBER(12,0),
    CONFIDENCE_SCORE         NUMBER(5,4),
    GROUNDEDNESS_SCORE       NUMBER(5,4),
    -- human in the loop
    REVIEW_STATUS            VARCHAR(24),            -- AUTO_APPROVED | PENDING_REVIEW |
                                                     -- APPROVED | REJECTED
    REVIEWED_BY              VARCHAR(128),
    REVIEWED_AT              TIMESTAMP_NTZ,
    REVIEW_NOTES             VARCHAR(2000),
    IS_PII_REDACTED          BOOLEAN,
    GENERATED_AT             TIMESTAMP_NTZ,
    EXPIRES_AT               TIMESTAMP_NTZ,          -- insights go stale; force refresh
    _CORRELATION_ID          VARCHAR(64),
    CONSTRAINT PK_AI_CUSTOMER_INSIGHTS PRIMARY KEY (INSIGHT_ID)
) COMMENT = 'Generated content. NOT a system of record. Never used as input to '
            'another generation without human approval.';

-- RAG corpus -----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ACME_EDP.AI.KB_DOCUMENT (
    DOCUMENT_ID              VARCHAR(64) NOT NULL,
    ARTICLE_ID               VARCHAR(64),
    TITLE                    VARCHAR(500),
    CATEGORY                 VARCHAR(120),
    OWNER                    VARCHAR(200),
    SOURCE_URI               VARCHAR(1000),
    CONTENT                  VARCHAR(16777216),
    CONTENT_HASH             VARCHAR(64),
    LAST_REVIEWED            DATE,
    IS_ACTIVE                BOOLEAN,
    _LOADED_AT               TIMESTAMP_NTZ,
    CONSTRAINT PK_KB_DOCUMENT PRIMARY KEY (DOCUMENT_ID)
);

CREATE TABLE IF NOT EXISTS ACME_EDP.AI.KB_CHUNK (
    CHUNK_ID                 VARCHAR(64) NOT NULL,
    DOCUMENT_ID              VARCHAR(64) NOT NULL,
    ARTICLE_ID               VARCHAR(64),
    CHUNK_INDEX              NUMBER(9,0),
    CHUNK_TEXT               VARCHAR(16777216),
    CHUNK_TOKENS             NUMBER(9,0),
    SECTION_TITLE            VARCHAR(500),
    -- Snowflake native vector type; the local warehouse stores the same vector
    -- as a JSON array (see local_warehouse/dialect.py).
    EMBEDDING                VECTOR(FLOAT, 768),
    EMBEDDING_MODEL          VARCHAR(128),
    EMBEDDED_AT              TIMESTAMP_NTZ,
    CONSTRAINT PK_KB_CHUNK PRIMARY KEY (CHUNK_ID)
);

-- Corpus term statistics.  Only the local (offline) embedder needs these: it is
-- a TF-IDF stand-in and therefore corpus-aware, which a real embedding model is
-- not.  The table is harmless in cloud mode and is useful there anyway for
-- vocabulary drift monitoring on the knowledge base.
CREATE TABLE IF NOT EXISTS ACME_EDP.AI.KB_TERM_STATS (
    TERM                     VARCHAR(128) NOT NULL,
    DOC_FREQ                 NUMBER(12,0),
    IDF                      NUMBER(12,6),
    N_DOCS                   NUMBER(12,0),
    COMPUTED_AT              TIMESTAMP_NTZ,
    CONSTRAINT PK_KB_TERM_STATS PRIMARY KEY (TERM)
);

-- Audit and evaluation --------------------------------------------------------
CREATE TABLE IF NOT EXISTS ACME_EDP.AI.AI_REQUEST_AUDIT (
    REQUEST_ID               VARCHAR(64) NOT NULL,
    CORRELATION_ID           VARCHAR(64),
    CUSTOMER_BK              VARCHAR(64),
    REQUESTED_BY_CLIENT_ID   VARCHAR(128),
    REQUESTED_BY_SUBJECT     VARCHAR(128),
    CAPABILITY               VARCHAR(64),
    PROMPT_TEMPLATE_ID       VARCHAR(64),
    PROMPT_VERSION           VARCHAR(16),
    MODEL_PROVIDER           VARCHAR(32),
    MODEL_NAME               VARCHAR(128),
    INPUT_TOKENS             NUMBER(12,0),
    OUTPUT_TOKENS            NUMBER(12,0),
    ESTIMATED_COST_USD       NUMBER(12,6),
    LATENCY_MS               NUMBER(12,0),
    OUTCOME                  VARCHAR(32),          -- SUCCESS | BLOCKED | ERROR | FALLBACK
    BLOCK_REASON             VARCHAR(500),
    PII_REDACTION_APPLIED    BOOLEAN,
    REQUESTED_AT             TIMESTAMP_NTZ,
    CONSTRAINT PK_AI_REQUEST_AUDIT PRIMARY KEY (REQUEST_ID)
) COMMENT = 'Every generative call, successful or not. Retention 24 months.';

CREATE TABLE IF NOT EXISTS ACME_EDP.AI.AI_EVALUATION_RESULT (
    EVALUATION_ID            VARCHAR(64) NOT NULL,
    EVALUATION_RUN_ID        VARCHAR(64),
    INSIGHT_ID               VARCHAR(64),
    TEST_CASE_ID             VARCHAR(64),
    METRIC_NAME              VARCHAR(64),          -- GROUNDEDNESS | RELEVANCE |
                                                   -- SAFETY | CONSISTENCY | PII_LEAKAGE
    METRIC_SCORE             NUMBER(5,4),
    THRESHOLD                NUMBER(5,4),
    PASSED                   BOOLEAN,
    EVALUATOR                VARCHAR(64),          -- DETERMINISTIC | LLM_JUDGE | HUMAN
    NOTES                    VARCHAR(2000),
    EVALUATED_AT             TIMESTAMP_NTZ,
    CONSTRAINT PK_AI_EVALUATION_RESULT PRIMARY KEY (EVALUATION_ID)
);
