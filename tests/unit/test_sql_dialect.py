"""The Snowflake -> DuckDB rewrite rules.

The value of these tests is not the regex coverage; it is that the *boundary*
stays honest.  If a Snowflake-only construct silently stopped being detected,
the local build would appear to run SQL it cannot actually run, and the
"same scripts in both places" claim would become false without anyone noticing.
"""
from __future__ import annotations

import pytest

from local_warehouse import dialect


class TestUnportableDetection:
    @pytest.mark.parametrize("sql,expected_fragment", [
        ("MERGE INTO t USING s ON t.k = s.k WHEN MATCHED THEN UPDATE SET a = 1", "MERGE"),
        ("CREATE OR REPLACE TASK t SCHEDULE = '1 minute' AS SELECT 1", "Snowpipe"),
        ("CREATE STREAM s ON TABLE t", "Snowpipe"),
        ("SELECT SNOWFLAKE.CORTEX.SENTIMENT(x) FROM t", "Cortex"),
        ("SELECT AI_COMPLETE('m', 'p')", "Cortex"),
        ("SELECT VECTOR_COSINE_SIMILARITY(a, b) FROM t", "VECTOR"),
        ("CREATE MASKING POLICY mp AS (v STRING) RETURNS STRING -> v", "masking"),
        ("CREATE ROW ACCESS POLICY rap AS (v STRING) RETURNS BOOLEAN -> TRUE", "row access"),
        ("CREATE WAREHOUSE wh WAREHOUSE_SIZE = 'XSMALL'", "account-level"),
        ("GRANT SELECT ON TABLE t TO ROLE r", "RBAC"),
        ("COPY INTO t FROM @stage", "COPY INTO"),
        ("SELECT * FROM t AT (TIMESTAMP => '2026-01-01')", "Time Travel"),
    ])
    def test_snowflake_only_constructs_are_detected(self, sql, expected_fragment):
        reason = dialect.unportable_reason(sql)
        assert reason is not None, f"{sql!r} should be flagged as Snowflake-only"
        assert expected_fragment.lower() in reason.lower()

    def test_portable_sql_is_not_flagged(self):
        assert dialect.unportable_reason(
            "INSERT INTO t SELECT a, b FROM s WHERE a > 1 QUALIFY ROW_NUMBER() "
            "OVER (PARTITION BY a ORDER BY b) = 1") is None

    def test_a_keyword_inside_a_comment_does_not_trigger_a_false_positive(self):
        # Otherwise every script that merely *explains* MERGE would be skipped,
        # and the explanatory comments in this repository would break the build.
        sql = "-- the incremental path uses MERGE INTO; this one does not\nSELECT 1"
        assert dialect.unportable_reason(sql) is None


class TestRewrites:
    def test_types_are_translated(self):
        out = dialect.translate(
            "CREATE TABLE t (a NUMBER(18,2), b TIMESTAMP_NTZ, c VARIANT, d STRING)")
        assert "DECIMAL(18,2)" in out
        assert "TIMESTAMP_NTZ" not in out
        assert "JSON" in out
        assert "VARIANT" not in out

    def test_datediff_becomes_date_diff(self):
        out = dialect.translate("SELECT DATEDIFF(day, a, b) FROM t")
        assert "date_diff('day', a, b)" in out

    def test_regexp_like_becomes_regexp_matches(self):
        assert "regexp_matches(" in dialect.translate("SELECT REGEXP_LIKE(x, '^a$')")

    def test_use_statements_are_removed(self):
        # Portable scripts fully qualify every object, so USE is noise that
        # DuckDB would reject.
        out = dialect.translate("USE DATABASE ACME_EDP;\nUSE SCHEMA RAW;\nSELECT 1;")
        assert "USE DATABASE" not in out
        assert "SELECT 1" in out

    def test_declared_primary_keys_are_stripped(self):
        # Snowflake does not enforce them; DuckDB does. Keeping them would change
        # behaviour, and the deliberate referential-integrity defects in the
        # sample data would fail to load instead of being reported.
        out = dialect.translate(
            "CREATE TABLE t (a VARCHAR, CONSTRAINT PK_T PRIMARY KEY (a))")
        assert "PRIMARY KEY" not in out
        assert "CREATE TABLE t (a VARCHAR" in out

    def test_object_comments_are_removed(self):
        out = dialect.translate("CREATE TABLE t (a VARCHAR) COMMENT = 'a table'")
        assert "COMMENT" not in out


class TestStatementSplitting:
    def test_splits_on_top_level_semicolons(self):
        assert dialect.split_statements("SELECT 1; SELECT 2;") == ["SELECT 1", "SELECT 2"]

    def test_a_semicolon_inside_a_string_literal_is_not_a_separator(self):
        stmts = dialect.split_statements("INSERT INTO t VALUES ('a; b'); SELECT 1;")
        assert len(stmts) == 2
        assert "'a; b'" in stmts[0]

    def test_escaped_quotes_are_handled(self):
        # This is the case that broke the data-dictionary seed: a business
        # definition containing "version''s".
        stmts = dialect.split_statements("INSERT INTO t VALUES ('it''s fine; really'); SELECT 2;")
        assert len(stmts) == 2
        assert "it''s fine; really" in stmts[0]

    def test_comments_are_ignored(self):
        stmts = dialect.split_statements("-- a comment with ; in it\nSELECT 1;\n/* also ; */ SELECT 2;")
        assert len(stmts) == 2

    def test_every_documented_rule_has_a_note(self):
        # The rewrite list is documentation as much as code: an undocumented
        # rule is an undocumented behavioural difference between environments.
        for rule in dialect.rule_documentation():
            assert rule["note"], f"rule {rule['pattern']} has no explanation"
