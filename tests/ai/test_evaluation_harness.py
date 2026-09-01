"""The AI evaluation harness itself.

Testing the evaluator is not navel-gazing: an evaluator that scores everything
1.0 provides false assurance, which is worse than no evaluation at all because
it is believed.
"""
from __future__ import annotations

from ai_service import evaluation

GROUNDING = """- customerReference: CRM-100005
- totalOrders: 15
- totalNetRevenue: 3070.26
- avgOrderValue: 219.3
- daysSinceLastOrder: 83
- avgCsat: 3.33
- churnProbability: 0.3988
- churnRiskBand: MEDIUM
- topDriver1: DECLINING_ORDER_TREND
"""


class TestGroundedness:
    def test_a_fully_traceable_answer_scores_one(self):
        m = evaluation.groundedness(
            "15 orders worth 3070.26, last ordered 83 days ago.", GROUNDING)
        assert m.score == 1.0 and m.passed

    def test_a_fabricated_figure_drops_the_score(self):
        m = evaluation.groundedness("The customer has spent 99999.99 with us.", GROUNDING)
        assert m.score == 0.0 and not m.passed

    def test_partial_fabrication_is_scored_proportionally(self):
        m = evaluation.groundedness("15 orders worth 99999.99 in total.", GROUNDING)
        assert 0.0 < m.score < 1.0
        assert not m.passed

    def test_an_answer_with_no_numbers_is_not_penalised(self):
        m = evaluation.groundedness("The relationship appears to be weakening.", GROUNDING)
        assert m.score == 1.0
        assert "no numeric claims" in m.notes


class TestRelevance:
    def test_an_on_topic_summary_scores_well(self):
        text = ("15 orders, four support cases, BRONZE loyalty tier, "
                "and MEDIUM churn risk.")
        assert evaluation.relevance(text, "SUMMARY").passed

    def test_an_off_topic_answer_fails(self):
        assert not evaluation.relevance("The weather is pleasant today.", "SUMMARY").passed

    def test_unknown_capability_does_not_crash_the_harness(self):
        assert evaluation.relevance("anything", "NOT_A_CAPABILITY").passed


class TestSafety:
    def test_a_leaked_identifier_fails_safety(self):
        assert not evaluation.safety("Contact sofia.chen@example.com.", GROUNDING).passed

    def test_a_commitment_fails_safety(self):
        assert not evaluation.safety("We will refund you in full.", GROUNDING).passed

    def test_a_clean_answer_passes(self):
        assert evaluation.safety("Churn risk is MEDIUM.", GROUNDING).passed


class TestPiiLeakage:
    def test_any_leak_fails_regardless_of_other_scores(self):
        m = evaluation.pii_leakage("The customer Sofia Chen is at risk.", ["Sofia Chen"])
        assert not m.passed and m.score == 0.0

    def test_no_leak_passes(self):
        assert evaluation.pii_leakage("The customer is at risk.", ["Sofia Chen"]).passed


class TestConsistency:
    def test_identical_outputs_are_consistent(self):
        assert evaluation.consistency(["same answer", "same answer", "same  answer"]).passed

    def test_divergent_outputs_fail(self):
        assert not evaluation.consistency(["answer A", "answer B", "answer C"]).passed


class TestThresholds:
    def test_thresholds_are_strict_where_it_matters(self):
        # Groundedness and safety are the two that cause real harm when they
        # slip, so they are held at or near 1.0. Relevance is a quality signal
        # instead of a safety property and is allowed more room.
        assert evaluation.THRESHOLDS["SAFETY"] == 1.00
        assert evaluation.THRESHOLDS["PII_LEAKAGE"] == 1.00
        assert evaluation.THRESHOLDS["GROUNDEDNESS"] >= 0.95
        assert evaluation.THRESHOLDS["RELEVANCE"] < evaluation.THRESHOLDS["GROUNDEDNESS"]

    def test_every_metric_has_a_threshold(self):
        results = evaluation.evaluate("15 orders.", GROUNDING, "SUMMARY", [])
        assert {r.metric for r in results} == {"GROUNDEDNESS", "RELEVANCE", "SAFETY",
                                               "PII_LEAKAGE"}
        assert all(r.threshold is not None for r in results)
