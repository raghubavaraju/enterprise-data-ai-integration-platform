"""The data quality suite must actually find the planted defects.

A DQ suite that always reports green is indistinguishable from one that is not
running.  ``sample-data/`` therefore contains eight deliberate defects, listed in
``snowflake/09-data-quality/expected-results.md``, and these tests assert that
each one is caught, classified at the right severity, and handled the right way.
"""
from __future__ import annotations

import pytest


@pytest.fixture(scope="module")
def dq_results(warehouse):
    from local_warehouse.dq_runner import run_all
    run_all()
    rows = warehouse.execute("""
        SELECT RULE_ID, SEVERITY, ROWS_FAILED, STATUS
        FROM ACME_EDP.GOVERNANCE.V_DQ_LATEST""").fetchall()
    return {r[0]: {"severity": r[1], "failed": r[2], "status": r[3]} for r in rows}


EXPECTED_FAILURES = {
    "DQ-C-001":  {"failed": 1, "status": "FAIL", "defect": "customer with a null business key"},
    "DQ-O-002":  {"failed": 1, "status": "FAIL", "defect": "order with a negative amount"},
    "DQ-O-003":  {"failed": 1, "status": "FAIL", "defect": "order dated in the future"},
    "DQ-C-002":  {"failed": 2, "status": "WARN", "defect": "two malformed e-mail addresses"},
    "DQ-C-005":  {"failed": 1, "status": "WARN", "defect": "fuzzy duplicate customer"},
    "DQ-L-003":  {"failed": 1, "status": "WARN", "defect": "redeemed points exceed earned"},
    "DQ-O-006":  {"failed": 1, "status": "WARN", "defect": "order for a non-existent customer"},
    "DQ-OI-003": {"failed": 1, "status": "WARN", "defect": "line for a non-existent product"},
}


class TestPlantedDefectsAreFound:
    @pytest.mark.parametrize("rule_id,expected", EXPECTED_FAILURES.items(),
                             ids=lambda v: v if isinstance(v, str) else "")
    def test_rule_finds_exactly_the_planted_defect(self, dq_results, rule_id, expected):
        actual = dq_results[rule_id]
        assert actual["failed"] == expected["failed"], (
            f"{rule_id} ({expected['defect']}): expected {expected['failed']} failing rows, "
            f"got {actual['failed']}")
        assert actual["status"] == expected["status"]

    def test_every_other_rule_passes(self, dq_results):
        unexpected = {rid: r for rid, r in dq_results.items()
                      if r["status"] != "PASS" and rid not in EXPECTED_FAILURES}
        assert not unexpected, f"unexpected data quality failures: {unexpected}"

    def test_the_overall_tally_matches_the_documented_expectation(self, dq_results):
        # Mirrors the table in snowflake/09-data-quality/expected-results.md.
        tally = {}
        for r in dq_results.values():
            tally[r["status"]] = tally.get(r["status"], 0) + 1
        assert tally == {"PASS": 14, "WARN": 5, "FAIL": 3}

    def test_no_rule_errored(self, warehouse):
        # A rule whose SQL no longer parses is worse than a failing rule: it
        # looks like coverage while checking nothing.
        assert warehouse.execute("""
            SELECT COUNT(*) FROM ACME_EDP.GOVERNANCE.DQ_RESULT
            WHERE ROWS_FAILED < 0""").fetchone()[0] == 0


class TestSeverityBehaviour:
    def test_blocking_failures_never_reach_core(self, warehouse):
        # The whole point of BLOCKING: the row is quarantined, not loaded.
        assert warehouse.execute("""
            SELECT COUNT(*) FROM ACME_EDP.CORE.SALES_ORDER
            WHERE ORDER_AMOUNT < 0 OR ORDER_DATE > CURRENT_DATE""").fetchone()[0] == 0

    def test_warning_rows_do_load(self, warehouse):
        # A malformed e-mail makes the row unusable for identity matching, not
        # unusable altogether. Rejecting it would lose a real customer.
        assert warehouse.execute("""
            SELECT COUNT(*) FROM ACME_EDP.CORE.CUSTOMER
            WHERE CUSTOMER_BK IN (SELECT CUSTOMER_BK FROM ACME_EDP.STAGING.STG_CUSTOMER
                                   WHERE EMAIL_IS_VALID = FALSE)""").fetchone()[0] > 0

    def test_rejected_rows_are_quarantined_not_dropped(self, warehouse):
        # Silent data loss is the failure mode that destroys trust in a platform.
        rejects = warehouse.execute("""
            SELECT RULE_ID, COUNT(*) FROM ACME_EDP.RAW.RAW_REJECTED_RECORDS
            GROUP BY RULE_ID ORDER BY RULE_ID""").fetchall()
        found = {r[0] for r in rejects}
        assert {"DQ-C-001", "DQ-O-002", "DQ-O-003", "DQ-C-005"} <= found

    def test_quarantined_rows_carry_a_reason_and_a_correlation_id(self, warehouse):
        assert warehouse.execute("""
            SELECT COUNT(*) FROM ACME_EDP.RAW.RAW_REJECTED_RECORDS
            WHERE REJECT_REASON IS NULL OR _CORRELATION_ID IS NULL""").fetchone()[0] == 0


class TestRuleCatalogue:
    def test_rules_are_data_not_code(self, warehouse):
        # Stored as rows so a steward can add one without a deployment, and so
        # the scorecard can render itself.
        assert warehouse.execute(
            "SELECT COUNT(*) FROM ACME_EDP.GOVERNANCE.DQ_RULE WHERE IS_ACTIVE").fetchone()[0] == 22

    def test_every_rule_has_an_owner_and_a_dimension(self, warehouse):
        assert warehouse.execute("""
            SELECT COUNT(*) FROM ACME_EDP.GOVERNANCE.DQ_RULE
            WHERE OWNER IS NULL OR DIMENSION IS NULL OR SEVERITY IS NULL""").fetchone()[0] == 0

    def test_all_six_quality_dimensions_are_covered(self, warehouse):
        # Timeliness in particular: it is the dimension teams skip, and it
        # produces the most damaging kind of wrong answer - a number that is
        # internally consistent, passes every other check, and describes
        # last week.
        dims = {r[0] for r in warehouse.execute(
            "SELECT DISTINCT DIMENSION FROM ACME_EDP.GOVERNANCE.DQ_RULE "
            "WHERE IS_ACTIVE").fetchall()}
        assert dims == {"COMPLETENESS", "VALIDITY", "UNIQUENESS", "CONSISTENCY",
                        "ACCURACY", "TIMELINESS"}

    def test_blocking_is_used_sparingly(self, warehouse):
        # A platform that rejects a day's orders over two bad postcodes does not
        # get trusted with the next system.
        blocking, total = warehouse.execute("""
            SELECT SUM(CASE WHEN SEVERITY = 'BLOCKING' THEN 1 ELSE 0 END), COUNT(*)
            FROM ACME_EDP.GOVERNANCE.DQ_RULE WHERE IS_ACTIVE""").fetchone()
        assert blocking / total <= 0.5
