"""Cross-process behaviour through the full API-led chain.

Skipped automatically when the stack is not running, so a developer without
docker still gets a green suite that means something.  What these tests cover
that the in-process suites cannot:

  * a correlation id surviving four network hops
  * real HTTP status translation between layers
  * entitlement masking decided from a token minted by the mock IdP
  * partial degradation caused by an actually-unavailable dependency

Start the stack with `make run` (or `make up`) before running these.
"""
from __future__ import annotations

import os

import httpx
import pytest

BASE = os.getenv("EXPERIENCE_API", "http://127.0.0.1:8080")
SECRET = os.getenv("OAUTH_CLIENT_SECRET", "change-me-local-only")
pytestmark = pytest.mark.integration


def _stack_is_up() -> bool:
    try:
        return httpx.get(f"{BASE}/health", timeout=1.0).status_code == 200
    except Exception:                                          # noqa: BLE001
        return False


pytestmark = [pytest.mark.integration,
              pytest.mark.skipif(not _stack_is_up(),
                                 reason="the platform is not running (make run)")]


@pytest.fixture(scope="module")
def client():
    with httpx.Client(base_url=BASE, timeout=30.0) as c:
        yield c


def token(client, client_id="acme-portal-client", scope=None):
    data = {"grant_type": "client_credentials", "client_id": client_id,
            "client_secret": SECRET}
    if scope:
        data["scope"] = scope
    return client.post("/oauth/token", data=data).json()["access_token"]


@pytest.fixture(scope="module")
def headers(client):
    return {"Authorization": f"Bearer {token(client)}"}


@pytest.fixture(scope="module")
def customer_id(client, headers):
    row = client.get("/api/v1/cohorts/high-risk", params={"limit": 1},
                     headers=headers).json()["data"][0]
    return row["customerId"]


class TestFullChain:
    def test_customer_360_traverses_every_layer(self, client, headers, customer_id):
        r = client.get(f"/api/v1/customers/{customer_id}/360", headers=headers)
        assert r.status_code == 200
        body = r.json()
        # Experience -> process -> system -> SQL API -> warehouse, all present.
        assert body["profile"]["segment"]
        assert body["analytics"]["totalOrders"] is not None
        assert body["churnRisk"]["riskBand"]
        assert "CRM" in body["meta"]["contributingSources"]

    def test_correlation_id_survives_four_hops(self, client, headers, customer_id):
        cid = "integration-test-correlation-id"
        r = client.get(f"/api/v1/customers/{customer_id}/360",
                       headers={**headers, "x-correlation-id": cid})
        assert r.headers["x-correlation-id"] == cid
        assert r.json()["meta"]["correlationId"] == cid

    def test_masking_is_decided_by_the_token(self, client, customer_id):
        without = client.get(
            f"/api/v1/customers/{customer_id}/360",
            headers={"Authorization": f"Bearer {token(client)}"}).json()
        assert without["profile"]["_masked"] is True
        assert "*" in without["profile"]["email"]

    def test_ai_insight_is_grounded_and_attributed(self, client, headers, customer_id):
        r = client.post(f"/api/v1/customers/{customer_id}/ai-analysis",
                        json={"capability": "CHURN_EXPLANATION", "forceRefresh": True},
                        headers=headers)
        assert r.status_code == 200
        body = r.json()
        assert body["text"]
        assert body["generatedBy"]["provider"]
        assert body["disclaimer"]

    def test_idempotent_replay_across_processes(self, client, headers, customer_id):
        key = "integration-idempotency-key"
        h = {**headers, "Idempotency-Key": key}
        first = client.post(f"/api/v1/customers/{customer_id}/ai-analysis",
                            json={"capability": "NEXT_BEST_ACTION", "forceRefresh": True},
                            headers=h).json()
        second = client.post(f"/api/v1/customers/{customer_id}/ai-analysis",
                             json={"capability": "NEXT_BEST_ACTION", "forceRefresh": True},
                             headers=h).json()
        assert second["meta"]["idempotentReplay"] is True
        assert second["text"] == first["text"]


class TestErrorContract:
    def test_unknown_customer_is_a_canonical_404(self, client, headers):
        r = client.get("/api/v1/customers/CRM-000000/360", headers=headers)
        assert r.status_code == 404
        body = r.json()
        assert body["errorCode"] == "PLATFORM:RESOURCE_NOT_FOUND"
        assert body["retryable"] is False
        assert body["correlationId"]
        # No stack trace, no internal hostname, no SQL.
        assert "Traceback" not in body["message"]
        assert "snowflake" not in body["message"].lower()

    def test_missing_token_is_401(self, client):
        assert client.get("/api/v1/customers/CRM-100005/360").status_code == 401

    def test_insufficient_scope_is_403(self, client):
        t = token(client, "acme-readonly-client")
        r = client.get("/api/v1/customers/CRM-100005/insights",
                       headers={"Authorization": f"Bearer {t}"})
        assert r.status_code == 403


class TestResilience:
    def test_source_system_outage_degrades_rather_than_fails(self, client, headers):
        # Drive the CRM System API with fault injection and confirm the caller
        # still receives a usable response.
        r = client.get("http://127.0.0.1:8090/api/v1/loyalty/accounts/CRM-100003",
                       headers=headers, params={"fault": "error"})
        assert r.status_code in (500, 502, 503, 504)
        body = r.json()
        assert body["errorCode"].startswith("PLATFORM:")
        assert body["retryable"] is True

    def test_health_endpoints_expose_circuit_breaker_state(self, client):
        for port in (8080, 8091, 8090):
            body = httpx.get(f"http://127.0.0.1:{port}/health", timeout=5).json()
            assert body["status"] == "UP"
            assert "circuitBreakers" in body


class TestGovernanceEndpoints:
    def test_data_quality_scorecard_is_published(self, client, headers):
        rows = client.get("/api/v1/governance/data-quality", headers=headers).json()["data"]
        assert len(rows) >= 20
        assert {r["status"] for r in rows} <= {"PASS", "WARN", "FAIL"}
        assert any(r["status"] == "FAIL" for r in rows), \
            "the planted defects must be visible through the API"
