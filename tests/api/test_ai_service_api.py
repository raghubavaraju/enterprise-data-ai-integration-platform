"""AI service contract and behaviour.

Runs in-process against the local deterministic provider.  What is being tested
is the *pipeline* - grounding, guardrails, scoring, review routing, audit - not
the eloquence of a model.
"""
from __future__ import annotations

import pytest


class TestAuthorisation:
    def test_no_token_is_401(self, ai_client, known_customer):
        r = ai_client.post(f"/api/v1/customers/{known_customer}/analysis",
                           json={"capability": "SUMMARY"})
        assert r.status_code == 401
        assert r.json()["errorCode"] == "PLATFORM:UNAUTHORIZED"

    def test_malformed_token_is_401(self, ai_client, known_customer):
        r = ai_client.post(f"/api/v1/customers/{known_customer}/analysis",
                           json={"capability": "SUMMARY"},
                           headers={"Authorization": "Bearer nonsense"})
        assert r.status_code == 401

    def test_token_without_ai_invoke_is_403(self, ai_client, known_customer, readonly_token):
        r = ai_client.post(f"/api/v1/customers/{known_customer}/analysis",
                           json={"capability": "SUMMARY"},
                           headers={"Authorization": f"Bearer {readonly_token}"})
        assert r.status_code == 403
        assert r.json()["errorCode"] == "PLATFORM:FORBIDDEN"


class TestValidation:
    def test_unknown_capability_is_400_with_the_allowed_list(self, ai_client, auth, known_customer):
        r = ai_client.post(f"/api/v1/customers/{known_customer}/analysis",
                           json={"capability": "PREDICT_LOTTERY"}, headers=auth)
        assert r.status_code == 400
        body = r.json()
        assert body["errorCode"] == "PLATFORM:VALIDATION_ERROR"
        assert "SUMMARY" in body["details"][0]["allowed"]

    def test_grounded_qa_requires_a_question(self, ai_client, auth, known_customer):
        r = ai_client.post(f"/api/v1/customers/{known_customer}/analysis",
                           json={"capability": "GROUNDED_QA"}, headers=auth)
        assert r.status_code == 400

    def test_unknown_customer_is_404(self, ai_client, auth):
        r = ai_client.post("/api/v1/customers/CRM-000000/analysis",
                           json={"capability": "SUMMARY"}, headers=auth)
        assert r.status_code == 404


class TestGeneration:
    @pytest.mark.parametrize("capability",
                             ["SUMMARY", "CHURN_EXPLANATION", "NEXT_BEST_ACTION", "SENTIMENT"])
    def test_each_capability_produces_a_governed_insight(self, ai_client, auth,
                                                         at_risk_customer, capability):
        r = ai_client.post(f"/api/v1/customers/{at_risk_customer}/analysis",
                           json={"capability": capability, "forceRefresh": True}, headers=auth)
        assert r.status_code == 200
        body = r.json()
        assert body["insightType"] == capability
        assert body["generatedText"].strip()
        # Provenance is not optional: an insight nobody can trace is an insight
        # nobody can defend.
        assert body["model"]["promptTemplateId"]
        assert body["model"]["promptVersion"]
        assert body["grounding"]["sourceView"].endswith("V_CUSTOMER_AI_CONTEXT")
        assert body["quality"]["groundedness"] is not None
        assert body["review"]["status"] in ("AUTO_APPROVED", "PENDING_REVIEW")

    def test_next_best_action_always_requires_human_approval(self, ai_client, auth,
                                                             at_risk_customer):
        # The platform recommends; a person decides. This is the single
        # human-in-the-loop rule that is not negotiable.
        r = ai_client.post(f"/api/v1/customers/{at_risk_customer}/analysis",
                           json={"capability": "NEXT_BEST_ACTION", "forceRefresh": True},
                           headers=auth)
        assert r.json()["review"]["requiresHumanApproval"] is True

    def test_recommended_action_comes_from_the_approved_list(self, ai_client, auth,
                                                             at_risk_customer):
        approved = {a["code"] for a in
                    ai_client.get("/api/v1/capabilities").json()["approvedActions"]}
        r = ai_client.post(f"/api/v1/customers/{at_risk_customer}/analysis",
                           json={"capability": "NEXT_BEST_ACTION", "forceRefresh": True},
                           headers=auth)
        assert r.json()["structured"]["action"] in approved

    def test_a_second_call_is_served_from_cache(self, ai_client, auth, known_customer):
        # Caching is a cost control, not a latency optimisation: a repeated
        # question about an unchanged customer must not be paid for twice.
        first = ai_client.post(f"/api/v1/customers/{known_customer}/analysis",
                               json={"capability": "SUMMARY", "forceRefresh": True},
                               headers=auth).json()
        second = ai_client.post(f"/api/v1/customers/{known_customer}/analysis",
                                json={"capability": "SUMMARY"}, headers=auth).json()
        assert first["cached"] is False
        assert second["cached"] is True
        assert second["generatedText"] == first["generatedText"]

    def test_partial_failure_does_not_fail_the_bundle(self, ai_client, auth, known_customer):
        r = ai_client.get(f"/api/v1/customers/{known_customer}/insights",
                          params={"types": "SUMMARY,NOT_A_CAPABILITY"}, headers=auth)
        assert r.status_code == 200
        body = r.json()
        assert len(body["insights"]) == 1
        assert body["failures"][0]["capability"] == "NOT_A_CAPABILITY"


class TestGroundingTransparency:
    def test_grounding_endpoint_shows_exactly_what_the_model_is_told(self, ai_client, auth,
                                                                     known_customer):
        r = ai_client.get(f"/api/v1/customers/{known_customer}/grounding", headers=auth)
        assert r.status_code == 200
        body = r.json()
        assert body["facts"]["customerReference"] == known_customer
        assert "FACTS" not in body["renderedFactsBlock"]  # it is the block, not the label
        assert "- totalOrders:" in body["renderedFactsBlock"]

    def test_grounding_contains_no_direct_identifiers(self, ai_client, auth, known_customer,
                                                      warehouse):
        # The AI context view has no name, e-mail, phone or date of birth in it
        # at all - so no code path can leak them by forgetting a filter.
        row = warehouse.execute(
            "SELECT FULL_NAME, EMAIL, PHONE FROM ACME_EDP.ANALYTICS.CUSTOMER_360 "
            "WHERE CUSTOMER_BK = ?", [known_customer]).fetchone()
        blob = ai_client.get(f"/api/v1/customers/{known_customer}/grounding",
                             headers=auth).text
        for value in row:
            if value:
                assert str(value) not in blob, f"{value!r} must never reach the model"


class TestAudit:
    def test_every_call_is_audited(self, ai_client, auth, known_customer, warehouse):
        before = warehouse.execute(
            "SELECT COUNT(*) FROM ACME_EDP.AI.AI_REQUEST_AUDIT").fetchone()[0]
        ai_client.post(f"/api/v1/customers/{known_customer}/analysis",
                       json={"capability": "SUMMARY", "forceRefresh": True}, headers=auth)
        after = warehouse.execute(
            "SELECT COUNT(*) FROM ACME_EDP.AI.AI_REQUEST_AUDIT").fetchone()[0]
        assert after == before + 1

    def test_audit_records_cost_and_attribution(self, ai_client, auth, known_customer, warehouse):
        ai_client.post(f"/api/v1/customers/{known_customer}/analysis",
                       json={"capability": "SUMMARY", "forceRefresh": True}, headers=auth)
        row = warehouse.execute("""
            SELECT REQUESTED_BY_CLIENT_ID, CAPABILITY, INPUT_TOKENS, OUTPUT_TOKENS,
                   ESTIMATED_COST_USD, OUTCOME, CORRELATION_ID
            FROM ACME_EDP.AI.AI_REQUEST_AUDIT ORDER BY REQUESTED_AT DESC LIMIT 1""").fetchone()
        client_id, capability, tin, tout, cost, outcome, corr = row
        assert client_id == "acme-portal-client"
        assert capability == "SUMMARY"
        assert tin > 0 and tout > 0
        assert cost is not None
        assert outcome == "SUCCESS"
        assert corr

    def test_evaluation_results_are_persisted(self, ai_client, auth, known_customer, warehouse):
        ai_client.post(f"/api/v1/customers/{known_customer}/analysis",
                       json={"capability": "SUMMARY", "forceRefresh": True}, headers=auth)
        metrics = {r[0] for r in warehouse.execute(
            "SELECT DISTINCT METRIC_NAME FROM ACME_EDP.AI.AI_EVALUATION_RESULT").fetchall()}
        assert {"GROUNDEDNESS", "RELEVANCE", "SAFETY", "PII_LEAKAGE"} <= metrics


class TestOperations:
    def test_health_reports_the_provider_in_use(self, ai_client):
        body = ai_client.get("/health").json()
        assert body["status"] == "UP"
        assert body["provider"] == "local"

    def test_correlation_id_is_echoed(self, ai_client, auth, known_customer):
        r = ai_client.get(f"/api/v1/customers/{known_customer}/grounding",
                          headers={**auth, "x-correlation-id": "test-corr-42"})
        assert r.headers["x-correlation-id"] == "test-corr-42"

    def test_capabilities_endpoint_publishes_prompt_versions(self, ai_client):
        body = ai_client.get("/api/v1/capabilities").json()
        assert body["promptLibraryVersion"]
        assert all(c["promptVersion"] for c in body["capabilities"])
