-- =============================================================================
-- 04-03  Knowledge-base embedding refresh      [Snowflake only]
-- =============================================================================
-- Re-chunks and re-embeds only the articles whose content hash changed.
--
-- The content hash is the whole design. Re-embedding an unchanged corpus every
-- night is pure Cortex spend for no benefit, and on a corpus of any size it is
-- the largest single line on the AI bill. Change-triggered rather than
-- schedule-triggered.
--
-- The local equivalent is services/ai_service/rag.py::build_corpus, which does
-- the same thing with the offline embedder.
-- =============================================================================

USE DATABASE ACME_EDP;
USE SCHEMA AI;

CREATE OR REPLACE PROCEDURE AI.SP_REFRESH_KB_EMBEDDINGS()
RETURNS VARCHAR
LANGUAGE SQL
EXECUTE AS OWNER
AS
$$
DECLARE
    changed INTEGER DEFAULT 0;
    chunks  INTEGER DEFAULT 0;
BEGIN
    -- 1 / Register or update documents whose content actually changed.
    MERGE INTO ACME_EDP.AI.KB_DOCUMENT AS t
    USING (
        SELECT
            'DOC-' || ARTICLE_ID              AS DOCUMENT_ID,
            ARTICLE_ID, TITLE, CATEGORY, OWNER, SOURCE_URI, CONTENT,
            MD5(CONTENT)                      AS CONTENT_HASH,
            TRY_TO_DATE(LAST_REVIEWED)        AS LAST_REVIEWED
        FROM ACME_EDP.RAW.RAW_SUP_KNOWLEDGE_ARTICLE
    ) AS s
       ON t.DOCUMENT_ID = s.DOCUMENT_ID
    WHEN MATCHED AND t.CONTENT_HASH <> s.CONTENT_HASH THEN UPDATE SET
        t.TITLE = s.TITLE, t.CATEGORY = s.CATEGORY, t.OWNER = s.OWNER,
        t.CONTENT = s.CONTENT, t.CONTENT_HASH = s.CONTENT_HASH,
        t.LAST_REVIEWED = s.LAST_REVIEWED, t._LOADED_AT = CURRENT_TIMESTAMP()
    WHEN NOT MATCHED THEN INSERT
        (DOCUMENT_ID, ARTICLE_ID, TITLE, CATEGORY, OWNER, SOURCE_URI, CONTENT,
         CONTENT_HASH, LAST_REVIEWED, IS_ACTIVE, _LOADED_AT)
        VALUES (s.DOCUMENT_ID, s.ARTICLE_ID, s.TITLE, s.CATEGORY, s.OWNER, s.SOURCE_URI,
                s.CONTENT, s.CONTENT_HASH, s.LAST_REVIEWED, TRUE, CURRENT_TIMESTAMP());

    SELECT COUNT(*) INTO :changed FROM ACME_EDP.AI.KB_DOCUMENT
     WHERE _LOADED_AT >= DATEADD(minute, -5, CURRENT_TIMESTAMP());

    IF (changed = 0) THEN
        RETURN 'SUCCESS: no article changed; embeddings not regenerated';
    END IF;

    -- 2 / Drop the chunks of changed documents only.
    DELETE FROM ACME_EDP.AI.KB_CHUNK
     WHERE DOCUMENT_ID IN (SELECT DOCUMENT_ID FROM ACME_EDP.AI.KB_DOCUMENT
                            WHERE _LOADED_AT >= DATEADD(minute, -5, CURRENT_TIMESTAMP()));

    -- 3 / Re-chunk and embed.
    --
    -- SPLIT_TEXT_RECURSIVE_CHARACTER splits on paragraph boundaries before
    -- falling back to characters, which is what keeps a policy rule and its
    -- exception in the same chunk. Slicing at a fixed offset is how a RAG system
    -- ends up citing "returns within 30 days" while omitting "except...".
    INSERT INTO ACME_EDP.AI.KB_CHUNK
        (CHUNK_ID, DOCUMENT_ID, ARTICLE_ID, CHUNK_INDEX, CHUNK_TEXT, CHUNK_TOKENS,
         SECTION_TITLE, EMBEDDING, EMBEDDING_MODEL, EMBEDDED_AT)
    SELECT
        d.DOCUMENT_ID || '-C' || LPAD(c.INDEX, 3, '0'),
        d.DOCUMENT_ID, d.ARTICLE_ID, c.INDEX,
        c.VALUE::VARCHAR,
        LENGTH(c.VALUE::VARCHAR) / 4,
        d.TITLE,
        SNOWFLAKE.CORTEX.EMBED_TEXT_768('snowflake-arctic-embed-m', c.VALUE::VARCHAR),
        'snowflake-arctic-embed-m',
        CURRENT_TIMESTAMP()
    FROM ACME_EDP.AI.KB_DOCUMENT d,
         LATERAL FLATTEN(input => SNOWFLAKE.CORTEX.SPLIT_TEXT_RECURSIVE_CHARACTER(
                                      d.CONTENT, 'markdown', 450, 50)) c
    WHERE d.IS_ACTIVE = TRUE
      AND d._LOADED_AT >= DATEADD(minute, -5, CURRENT_TIMESTAMP());

    SELECT COUNT(*) INTO :chunks FROM ACME_EDP.AI.KB_CHUNK;
    RETURN 'SUCCESS: ' || changed || ' articles re-embedded, ' || chunks || ' chunks total';
END;
$$;
