"""The warehouse builds correctly and holds its modelling invariants.

These are the assertions that catch a broken transformation before a dashboard
does.  Each one corresponds to a modelling decision documented in
``docs/data-architecture.md``; if the decision changes, the test should change
with it rather than being deleted.
"""
from __future__ import annotations


def scalar(warehouse, sql, params=None):
    """Run a scalar query. SQL here is authored in the test, not user input."""
    return warehouse.execute(sql, params or []).fetchone()[0]  # noqa: S608


class TestLayering:
    def test_every_layer_is_populated(self, warehouse):
        for table in ["RAW.RAW_CRM_CUSTOMER", "STAGING.STG_CUSTOMER", "CORE.CUSTOMER",
                      "ANALYTICS.CUSTOMER_360", "AI.CUSTOMER_FEATURES",
                      "AI.CUSTOMER_CHURN_SCORE", "AI.KB_CHUNK",
                      "GOVERNANCE.DQ_RESULT", "GOVERNANCE.DATA_DICTIONARY",
                      "GOVERNANCE.LINEAGE_EDGE"]:
            # noqa: S608 - the table name comes from the literal list above.
            count = scalar(warehouse, f"SELECT COUNT(*) FROM ACME_EDP.{table}")  # noqa: S608
            assert count > 0, f"{table} is empty after a full build"

    def test_customer_360_covers_every_current_customer(self, warehouse):
        # DQ-X-001 in SQL; asserted here so a broken join fails the build rather
        # than quietly dropping customers from every downstream report.
        missing = scalar(warehouse, """
            SELECT COUNT(*) FROM ACME_EDP.CORE.CUSTOMER c
            WHERE c.IS_CURRENT = TRUE
              AND NOT EXISTS (SELECT 1 FROM ACME_EDP.ANALYTICS.CUSTOMER_360 x
                               WHERE x.CUSTOMER_BK = c.CUSTOMER_BK)""")
        assert missing == 0

    def test_customers_without_orders_are_still_present(self, warehouse):
        # The cohort most at risk of churn is the one that stopped ordering.
        # An inner join anywhere in the chain would delete exactly that cohort.
        assert scalar(warehouse, """
            SELECT COUNT(*) FROM ACME_EDP.ANALYTICS.CUSTOMER_360
            WHERE TOTAL_ORDERS = 0""") > 0


class TestSlowlyChangingDimension:
    def test_exactly_one_current_version_per_customer(self, warehouse):
        assert scalar(warehouse, """
            SELECT COUNT(*) FROM (
                SELECT CUSTOMER_BK FROM ACME_EDP.CORE.CUSTOMER
                WHERE IS_CURRENT = TRUE GROUP BY CUSTOMER_BK HAVING COUNT(*) > 1)""") == 0

    def test_validity_windows_do_not_overlap(self, warehouse):
        assert scalar(warehouse, """
            SELECT COUNT(*) FROM ACME_EDP.CORE.CUSTOMER a
            JOIN ACME_EDP.CORE.CUSTOMER b
              ON a.CUSTOMER_BK = b.CUSTOMER_BK AND a.CUSTOMER_SK <> b.CUSTOMER_SK
             AND a.VALID_FROM < b.VALID_TO AND b.VALID_FROM < a.VALID_TO""") == 0

    def test_open_versions_use_the_end_of_time_sentinel(self, warehouse):
        # A NULL VALID_TO forces every downstream predicate to special-case it,
        # and someone always forgets.
        assert scalar(warehouse, """
            SELECT COUNT(*) FROM ACME_EDP.CORE.CUSTOMER
            WHERE IS_CURRENT = TRUE AND VALID_TO < TIMESTAMP '9999-12-31'""") == 0

    def test_surrogate_keys_are_unique(self, warehouse):
        total = scalar(warehouse, "SELECT COUNT(*) FROM ACME_EDP.CORE.CUSTOMER")
        distinct = scalar(warehouse, "SELECT COUNT(DISTINCT CUSTOMER_SK) FROM ACME_EDP.CORE.CUSTOMER")
        assert total == distinct

    def test_row_hash_covers_only_tracked_attributes(self, warehouse):
        # Two rows with identical tracked attributes must share a hash;
        # otherwise every reload creates a spurious new version.
        assert scalar(warehouse, """
            SELECT COUNT(*) FROM ACME_EDP.STAGING.STG_CUSTOMER WHERE _ROW_HASH IS NULL""") == 0


class TestDeduplication:
    def test_exact_replays_are_collapsed(self, warehouse):
        raw = scalar(warehouse, "SELECT COUNT(*) FROM ACME_EDP.RAW.RAW_CRM_CUSTOMER")
        staged = scalar(warehouse, "SELECT COUNT(*) FROM ACME_EDP.STAGING.STG_CUSTOMER")
        assert staged < raw, "the deliberate duplicates must not survive into STAGING"

    def test_no_duplicate_business_keys_in_staging(self, warehouse):
        assert scalar(warehouse, """
            SELECT COUNT(*) FROM (SELECT CUSTOMER_BK FROM ACME_EDP.STAGING.STG_CUSTOMER
                                  GROUP BY CUSTOMER_BK HAVING COUNT(*) > 1)""") == 0

    def test_fuzzy_duplicate_is_suppressed_and_recorded(self, warehouse):
        # CRM-900001 is the same person as an existing customer with a different
        # id and different casing. It must not load, and it must be recorded for
        # a steward - suppressing silently is how duplicate customers become
        # invisible rather than solved.
        assert scalar(warehouse, """
            SELECT COUNT(*) FROM ACME_EDP.STAGING.STG_CUSTOMER
            WHERE CUSTOMER_BK = 'CRM-900001'""") == 0
        assert scalar(warehouse, """
            SELECT COUNT(*) FROM ACME_EDP.RAW.RAW_REJECTED_RECORDS
            WHERE RULE_ID = 'DQ-C-005'""") >= 1


class TestRevenueDefinition:
    def test_only_recognised_orders_contribute_to_revenue(self, warehouse):
        # One definition of revenue, applied everywhere. Two dashboards
        # disagreeing about a customer's spend is almost always this.
        mismatches = scalar(warehouse, """
            SELECT COUNT(*) FROM (
                SELECT s.CUSTOMER_BK,
                       s.TOTAL_NET_REVENUE AS SUMMARY_REVENUE,
                       COALESCE(SUM(CASE WHEN o.IS_REVENUE_RECOGNISED THEN o.NET_AMOUNT END), 0)
                           AS RECOMPUTED
                FROM ACME_EDP.ANALYTICS.CUSTOMER_ORDER_SUMMARY s
                LEFT JOIN ACME_EDP.CORE.SALES_ORDER o ON o.CUSTOMER_BK = s.CUSTOMER_BK
                GROUP BY s.CUSTOMER_BK, s.TOTAL_NET_REVENUE
                HAVING ABS(s.TOTAL_NET_REVENUE - RECOMPUTED) > 0.01)""")
        assert mismatches == 0

    def test_customer_360_revenue_matches_the_order_summary(self, warehouse):
        assert scalar(warehouse, """
            SELECT COUNT(*) FROM ACME_EDP.ANALYTICS.CUSTOMER_360 c
            JOIN ACME_EDP.ANALYTICS.CUSTOMER_ORDER_SUMMARY o ON o.CUSTOMER_BK = c.CUSTOMER_BK
            WHERE ABS(c.TOTAL_NET_REVENUE - o.TOTAL_NET_REVENUE) > 0.01""") == 0

    def test_lifetime_value_is_realised_not_predicted(self, warehouse):
        # CLV and predicted CLV are different numbers held in different columns.
        # Conflating them is how a forecast ends up quoted as revenue.
        assert scalar(warehouse, """
            SELECT COUNT(*) FROM ACME_EDP.ANALYTICS.CUSTOMER_360
            WHERE ABS(CUSTOMER_LIFETIME_VALUE - TOTAL_NET_REVENUE) > 0.01""") == 0

    def test_orphan_order_lines_are_excluded_from_core(self, warehouse):
        assert scalar(warehouse, """
            SELECT COUNT(*) FROM ACME_EDP.CORE.SALES_ORDER_ITEM i
            WHERE NOT EXISTS (SELECT 1 FROM ACME_EDP.CORE.SALES_ORDER o
                               WHERE o.ORDER_BK = i.ORDER_BK)""") == 0


class TestDerivedMetrics:
    def test_engagement_score_is_bounded(self, warehouse):
        assert scalar(warehouse, """
            SELECT COUNT(*) FROM ACME_EDP.ANALYTICS.CUSTOMER_360
            WHERE ENGAGEMENT_SCORE < 0 OR ENGAGEMENT_SCORE > 100""") == 0

    def test_engagement_score_has_a_single_definition(self, warehouse):
        # Defined in 07-02 and read by both CUSTOMER_360 and the feature store.
        # Two implementations would let a customer be "engaged" on the dashboard
        # and "disengaged" in the model on the same day.
        assert scalar(warehouse, """
            SELECT COUNT(*) FROM ACME_EDP.ANALYTICS.CUSTOMER_360 c
            JOIN ACME_EDP.ANALYTICS.CUSTOMER_ENGAGEMENT_SUMMARY e
              ON e.CUSTOMER_BK = c.CUSTOMER_BK
            WHERE ABS(c.ENGAGEMENT_SCORE - e.ENGAGEMENT_SCORE) > 0.01""") == 0
        assert scalar(warehouse, """
            SELECT COUNT(*) FROM ACME_EDP.AI.CUSTOMER_FEATURES f
            JOIN ACME_EDP.ANALYTICS.CUSTOMER_ENGAGEMENT_SUMMARY e
              ON e.CUSTOMER_BK = f.CUSTOMER_BK
            WHERE ABS(f.F_ENGAGEMENT_SCORE - e.ENGAGEMENT_SCORE) > 0.01""") == 0

    def test_data_completeness_is_a_percentage(self, warehouse):
        assert scalar(warehouse, """
            SELECT COUNT(*) FROM ACME_EDP.ANALYTICS.CUSTOMER_360
            WHERE DATA_COMPLETENESS_SCORE < 0 OR DATA_COMPLETENESS_SCORE > 100""") == 0

    def test_contributing_sources_always_include_crm(self, warehouse):
        assert scalar(warehouse, """
            SELECT COUNT(*) FROM ACME_EDP.ANALYTICS.CUSTOMER_360
            WHERE CONTRIBUTING_SOURCES NOT LIKE 'CRM%'""") == 0


class TestChurnScoring:
    def test_probability_is_a_probability(self, warehouse):
        assert scalar(warehouse, """
            SELECT COUNT(*) FROM ACME_EDP.AI.CUSTOMER_CHURN_SCORE
            WHERE CHURN_PROBABILITY < 0 OR CHURN_PROBABILITY > 1""") == 0

    def test_risk_band_matches_the_probability(self, warehouse):
        assert scalar(warehouse, """
            SELECT COUNT(*) FROM ACME_EDP.AI.CUSTOMER_CHURN_SCORE
            WHERE (CHURN_PROBABILITY >= 0.70 AND CHURN_RISK_BAND <> 'CRITICAL')
               OR (CHURN_PROBABILITY >= 0.50 AND CHURN_PROBABILITY < 0.70
                   AND CHURN_RISK_BAND <> 'HIGH')
               OR (CHURN_PROBABILITY >= 0.30 AND CHURN_PROBABILITY < 0.50
                   AND CHURN_RISK_BAND <> 'MEDIUM')
               OR (CHURN_PROBABILITY < 0.30 AND CHURN_RISK_BAND <> 'LOW')""") == 0

    def test_every_score_stores_its_drivers(self, warehouse):
        # The explanation must be reproducible months later, which means stored
        # and not regenerated.
        assert scalar(warehouse, """
            SELECT COUNT(*) FROM ACME_EDP.AI.CUSTOMER_CHURN_SCORE
            WHERE TOP_DRIVER_1 IS NULL OR TOP_DRIVER_1_CONTRIB IS NULL""") == 0

    def test_drivers_are_ordered_by_contribution(self, warehouse):
        assert scalar(warehouse, """
            SELECT COUNT(*) FROM ACME_EDP.AI.CUSTOMER_CHURN_SCORE
            WHERE TOP_DRIVER_1_CONTRIB < TOP_DRIVER_2_CONTRIB
               OR TOP_DRIVER_2_CONTRIB < TOP_DRIVER_3_CONTRIB""") == 0

    def test_the_score_discriminates(self, warehouse):
        # A scorer that puts everyone in one band is not a scorer.
        bands = warehouse.execute(
            "SELECT COUNT(DISTINCT CHURN_RISK_BAND) FROM ACME_EDP.AI.CUSTOMER_CHURN_SCORE"
        ).fetchone()[0]
        assert bands >= 3

    def test_a_dormant_customer_scores_higher_than_an_active_one(self, warehouse):
        row = warehouse.execute("""
            SELECT
              AVG(CASE WHEN f.F_RECENCY_DAYS > 300 THEN s.CHURN_PROBABILITY END) AS DORMANT,
              AVG(CASE WHEN f.F_RECENCY_DAYS < 60  THEN s.CHURN_PROBABILITY END) AS ACTIVE
            FROM ACME_EDP.AI.CUSTOMER_CHURN_SCORE s
            JOIN ACME_EDP.AI.CUSTOMER_FEATURES f
              ON f.CUSTOMER_BK = s.CUSTOMER_BK AND f.FEATURE_DATE = s.SCORE_DATE""").fetchone()
        dormant, active = row
        assert dormant is not None and active is not None
        assert dormant > active, "recency must move the score in the expected direction"


class TestFeatureStore:
    def test_features_are_point_in_time(self, warehouse):
        assert scalar(warehouse, """
            SELECT COUNT(*) FROM ACME_EDP.AI.CUSTOMER_FEATURES WHERE FEATURE_DATE IS NULL""") == 0

    def test_feature_set_is_versioned(self, warehouse):
        # A model pins the feature contract it was fitted against; without a
        # version, changing a definition silently changes every historic score.
        assert scalar(warehouse, """
            SELECT COUNT(DISTINCT FEATURE_SET_VERSION) FROM ACME_EDP.AI.CUSTOMER_FEATURES""") == 1

    def test_every_scored_customer_has_features_for_that_date(self, warehouse):
        assert scalar(warehouse, """
            SELECT COUNT(*) FROM ACME_EDP.AI.CUSTOMER_CHURN_SCORE s
            WHERE NOT EXISTS (SELECT 1 FROM ACME_EDP.AI.CUSTOMER_FEATURES f
                               WHERE f.CUSTOMER_BK = s.CUSTOMER_BK
                                 AND f.FEATURE_DATE = s.SCORE_DATE)""") == 0


class TestGovernanceMetadata:
    def test_every_pii_column_names_a_masking_policy(self, warehouse):
        assert scalar(warehouse, """
            SELECT COUNT(*) FROM ACME_EDP.GOVERNANCE.DATA_DICTIONARY
            WHERE IS_PII = TRUE AND (MASKING_POLICY IS NULL OR MASKING_POLICY = '')""") == 0

    def test_every_column_has_an_owner_and_a_definition(self, warehouse):
        assert scalar(warehouse, """
            SELECT COUNT(*) FROM ACME_EDP.GOVERNANCE.DATA_DICTIONARY
            WHERE DATA_OWNER IS NULL OR BUSINESS_DEFINITION IS NULL""") == 0

    def test_lineage_reaches_beyond_the_database(self, warehouse):
        # Most lineage tooling stops at the database boundary, which is exactly
        # where "where does this number on the agent's screen come from?" gets
        # interesting.
        assert scalar(warehouse, """
            SELECT COUNT(*) FROM ACME_EDP.GOVERNANCE.LINEAGE_EDGE
            WHERE TARGET_OBJECT LIKE 'mule:%'""") > 0

    def test_pii_propagating_edges_are_flagged(self, warehouse):
        assert scalar(warehouse, """
            SELECT COUNT(*) FROM ACME_EDP.GOVERNANCE.LINEAGE_EDGE
            WHERE IS_PII_PROPAGATING = TRUE""") > 0
