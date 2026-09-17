"""The three API-led layers, in-process, with their downstreams stubbed.

These cover the behaviour that distinguishes the layers from one another, which
is the whole architectural claim:

    system      normalises source quirks; speaks canonical vocabulary
    process     orchestrates and degrades; owns the business process
    experience  shapes and masks; owns the client contract

Downstream HTTP is stubbed at the ``DownstreamClient`` boundary rather than by
running the other services, so a failure here is a failure in this layer.
"""
from __future__ import annotations

import copy

import pytest
from fastapi.testclient import TestClient

from common.errors import DownstreamUnavailableError, NotFoundError


# ---------------------------------------------------------------------------
# Stubbing helper
# ---------------------------------------------------------------------------
class StubClient:
    """Stands in for DownstreamClient. Routes are matched by path prefix."""

    def __init__(self, name: str, routes: dict, failures: dict | None = None):
        self.name = name
        self.routes = routes
        self.failures = failures or {}
        self.calls: list[tuple[str, str]] = []

    async def request(self, method, path, **kwargs):
        self.calls.append((method, path))
        for prefix, exc in self.failures.items():
            if path.startswith(prefix):
                raise exc
        for prefix, payload in self.routes.items():
            if path.startswith(prefix):
                # A deep copy per call, because a real HTTP response is a fresh
                # object every time. Handing back the same dict lets one test's
                # in-place shaping leak into the next one - which is exactly the
                # kind of shared-state bug that makes a suite pass alone and fail
                # together.
                return copy.deepcopy(payload)
        raise NotFoundError(f"{self.name} has no stub for {path}")

    async def get(self, path, **kw):
        return await self.request("GET", path, **kw)

    async def post(self, path, **kw):
        return await self.request("POST", path, **kw)


class InProcessDataApi:
    """The Snowflake SQL API contract, served in-process by the data API.

    The system layer's warehouse dependency is the one downstream that must not
    be stubbed with a canned payload: these tests exist to prove that real
    warehouse column names never reach a consumer, which a stub would make
    vacuously true.

    So the real ``services/data_api`` application is mounted over an ASGI
    transport instead of over a socket. Same code path, same SQL, no running
    stack - which is what lets the suite be hermetic.
    """

    def __init__(self, token: str):
        from data_api import app as data_api_module
        self._app = data_api_module.app
        self._token = token

    async def request(self, method, path, *, json=None, params=None,
                      headers=None, retries=None):
        import httpx

        hdrs = {"Authorization": f"Bearer {self._token}", "accept": "application/json"}
        if headers:
            hdrs.update(headers)
        transport = httpx.ASGITransport(app=self._app)
        async with httpx.AsyncClient(transport=transport,
                                     base_url="http://data-api") as client:
            resp = await client.request(method, path, json=json, params=params,
                                        headers=hdrs)
        # Mirrors DownstreamClient's status mapping, because the layer under
        # test reacts to the exception type, not to the status code.
        if resp.status_code == 404:
            raise NotFoundError(f"data-api has no record for {path}.")
        if resp.status_code >= 500:
            raise DownstreamUnavailableError(f"data-api returned {resp.status_code}.")
        return resp.json() if resp.content else None

    async def get(self, path, **kw):
        return await self.request("GET", path, **kw)

    async def post(self, path, **kw):
        return await self.request("POST", path, **kw)


@pytest.fixture()
def system_client():
    from gateway import system_layer
    return TestClient(system_layer.app, raise_server_exceptions=False)


@pytest.fixture()
def warehouse_system_client(system_client, full_token, monkeypatch, warehouse):
    """A system layer whose warehouse downstream is the real data API."""
    from gateway import system_layer
    monkeypatch.setattr(system_layer, "snowflake", InProcessDataApi(full_token))
    return system_client


@pytest.fixture()
def process_app():
    from gateway import process_layer
    return process_layer


@pytest.fixture()
def experience_app():
    from gateway import experience_layer
    return experience_layer


@pytest.fixture()
def store_app():
    from gateway import store_experience_layer
    return store_experience_layer


# ---------------------------------------------------------------------------
# System layer
# ---------------------------------------------------------------------------
class TestSystemLayer:
    def test_loyalty_404_becomes_an_unambiguous_not_enrolled(self, system_client, auth,
                                                             monkeypatch):
        """The quirk this layer exists to absorb.

        The loyalty platform answers 404 both for "no such customer" and for
        "this customer never enrolled". Propagating that ambiguity would force
        every consumer to guess; translating it here is the layer's whole job.
        """
        from gateway import system_layer
        monkeypatch.setattr(system_layer, "loyalty",
                            StubClient("loyalty", {},
                                       {"/api/v1/loyalty-accounts": NotFoundError("nope")}))
        r = system_client.get("/api/v1/loyalty/accounts/CRM-100005", headers=auth)
        assert r.status_code == 200
        body = r.json()
        assert body["enrolled"] is False
        assert body["status"] == "NOT_ENROLLED"

    def test_crm_vocabulary_is_translated(self, system_client, auth, monkeypatch):
        from gateway import system_layer
        monkeypatch.setattr(system_layer, "crm", StubClient("crm", {
            "/api/v1/customers": {"customerId": "CRM-100005", "firstName": "Sofia",
                                  "lastName": "Chen", "email": "s@example.com",
                                  "customerSegment": "PREMIUM", "status": "ACTIVE"}}))
        body = system_client.get("/api/v1/crm/customers/CRM-100005", headers=auth).json()
        # The canonical name is `segment`; the CRM's `customerSegment` stops here.
        assert body["segment"] == "PREMIUM"
        assert "customerSegment" not in body
        assert body["sourceSystem"] == "CRM"

    def test_warehouse_column_names_never_reach_a_consumer(self, warehouse_system_client,
                                                           auth, known_customer):
        body = warehouse_system_client.get(
            f"/api/v1/snowflake/customers/{known_customer}/orders?limit=2",
            headers=auth).json()
        assert body["data"], "the sample customer must have orders"
        for key in body["data"][0]:
            assert key == key.lower() or not key.isupper(), \
                f"{key} is a database column name, not an API field"
        assert "orderId" in body["data"][0]

    def test_pagination_is_explicit(self, warehouse_system_client, auth, known_customer):
        page = warehouse_system_client.get(
            f"/api/v1/snowflake/customers/{known_customer}/orders?limit=1",
            headers=auth).json()["pagination"]
        # hasMore is published and not left for the client to infer from
        # offset + limit >= total, which is wrong the moment the underlying
        # collection changes between pages.
        assert page["total"] >= 1
        assert page["hasMore"] is (page["total"] > 1)
        assert page["limit"] == 1 and page["offset"] == 0

    def test_unknown_customer_is_404(self, warehouse_system_client, auth):
        r = warehouse_system_client.get("/api/v1/snowflake/customers/CRM-000000/360", headers=auth)
        assert r.status_code == 404

    def test_health_exposes_circuit_breaker_state(self, system_client):
        body = system_client.get("/health").json()
        assert body["status"] == "UP"
        assert isinstance(body["circuitBreakers"], list)


# ---------------------------------------------------------------------------
# Process layer
# ---------------------------------------------------------------------------
CORE_ROW = {
    "CUSTOMER_ID": "CRM-100005", "FULL_NAME": "Sofia Chen", "EMAIL": "sofia.chen@example.com",
    "PHONE": "+1-402-555-1005", "BIRTH_DATE": "1960-04-17", "CUSTOMER_SEGMENT": "PREMIUM",
    "CUSTOMER_STATUS": "ACTIVE", "PREFERRED_CHANNEL": "WEB", "MARKETING_OPT_IN": False,
    "CUSTOMER_SINCE": "2024-12-07", "TENURE_DAYS": 629, "PRIMARY_CITY": "Atlanta",
    "PRIMARY_STATE": "GA", "PRIMARY_COUNTRY": "US", "TOTAL_ORDERS": 15,
    "TOTAL_NET_REVENUE": 3070.26, "AVG_ORDER_VALUE": 219.3, "ORDER_FREQUENCY_PER_YEAR": 20.5,
    "LAST_ORDER_DATE": "2026-06-06", "DAYS_SINCE_LAST_ORDER": 83, "REVENUE_LAST_365D": 3070.26,
    "RETURN_RATE": 0.0, "TOTAL_CASES": 4, "OPEN_CASES": 1, "AVG_CSAT": 3.33,
    "TOP_CASE_TYPE": "DELIVERY_ISSUE", "LOYALTY_TIER": "BRONZE", "LOYALTY_STATUS": "ACTIVE",
    "LOYALTY_POINTS_BALANCE": 14085, "LOYALTY_ENROLLED_AT": "2021-07-07",
    "ENGAGEMENT_SCORE": 63.67, "CUSTOMER_LIFETIME_VALUE": 3070.26,
    "PREDICTED_CLV_12M": 2703.52, "VALUE_TIER": "HIGH", "DATA_COMPLETENESS_SCORE": 100,
    "CONTRIBUTING_SOURCES": "CRM,OMS,SUPPORT,LOYALTY", "AS_OF_TIMESTAMP": "2026-08-28T04:15:02",
}
CHURN_ROW = {"CHURN_PROBABILITY": 0.3988, "CHURN_RISK_BAND": "MEDIUM",
             "MODEL_NAME": "acme-churn-baseline", "MODEL_VERSION": "v1.2.0",
             "SCORING_METHOD": "RULE_BASED", "FEATURE_SET_VERSION": "v1.2.0",
             "TOP_DRIVER_1": "DECLINING_ORDER_TREND", "TOP_DRIVER_1_CONTRIB": 0.16,
             "TOP_DRIVER_2": "PURCHASE_RECENCY", "TOP_DRIVER_2_CONTRIB": 0.10,
             "TOP_DRIVER_3": "LOYALTY_INACTIVITY", "TOP_DRIVER_3_CONTRIB": 0.08,
             "SCORE_DATE": "2026-08-28"}
HEALTHY_ROUTES = {
    "/api/v1/snowflake/customers/CRM-100005/360": CORE_ROW,
    "/api/v1/snowflake/customers/CRM-100005/churn-risk": CHURN_ROW,
    "/api/v1/snowflake/customers/CRM-100005/orders": {
        "data": [{"orderId": "ORD-1", "netAmount": 199.75}],
        "pagination": {"limit": 10, "offset": 0, "total": 1, "hasMore": False}},
    "/api/v1/snowflake/customers/CRM-100005/cases": {"data": [{"caseId": "CAS-1"}]},
}


class TestProcessLayer:
    @pytest.fixture()
    def client(self, process_app, monkeypatch):
        monkeypatch.setattr(process_app, "system", StubClient("system-api", HEALTHY_ROUTES))
        monkeypatch.setattr(process_app, "ai",
                            StubClient("ai-service", {"/api/v1/customers": {"insights": [],
                                                                            "failures": []}}))
        return TestClient(process_app.app, raise_server_exceptions=False)

    def test_assembles_the_business_object(self, client, auth):
        body = client.get("/api/v1/customers/CRM-100005/360", headers=auth).json()
        assert body["profile"]["segment"] == "PREMIUM"
        assert body["analytics"]["totalOrders"] == 15
        assert body["churnRisk"]["riskBand"] == "MEDIUM"
        assert len(body["churnRisk"]["drivers"]) == 3
        assert body["partial"] is False

    def test_realised_and_predicted_value_stay_separate(self, client, auth):
        analytics = client.get("/api/v1/customers/CRM-100005/360",
                               headers=auth).json()["analytics"]
        assert analytics["customerLifetimeValue"] == 3070.26
        assert analytics["predictedClv12m"] == 2703.52

    def test_a_failed_dependency_degrades_the_response(self, process_app, monkeypatch, auth):
        monkeypatch.setattr(process_app, "system", StubClient(
            "system-api", HEALTHY_ROUTES,
            {"/api/v1/snowflake/customers/CRM-100005/orders":
                DownstreamUnavailableError("orders are down")}))
        client = TestClient(process_app.app, raise_server_exceptions=False)
        r = client.get("/api/v1/customers/CRM-100005/360", headers=auth)
        # 200, not 500: an agent with a customer on the phone needs what we have.
        assert r.status_code == 200
        body = r.json()
        assert body["partial"] is True
        assert body["degradedFields"][0]["field"] == "orders"
        assert body["degradedFields"][0]["errorCode"] == "PLATFORM:DOWNSTREAM_UNAVAILABLE"
        # Everything that did work is still there.
        assert body["profile"]["segment"] == "PREMIUM"
        assert body["churnRisk"] is not None

    def test_an_absent_churn_score_is_not_reported_as_degradation(self, process_app,
                                                                  monkeypatch, auth):
        monkeypatch.setattr(process_app, "system", StubClient(
            "system-api", HEALTHY_ROUTES,
            {"/api/v1/snowflake/customers/CRM-100005/churn-risk": NotFoundError("not scored")}))
        client = TestClient(process_app.app, raise_server_exceptions=False)
        body = client.get("/api/v1/customers/CRM-100005/360", headers=auth).json()
        assert body["churnRisk"] is None
        # Crying outage over an absent record is how the partial flag becomes
        # noise that operations learns to ignore.
        assert body["partial"] is False

    def test_the_core_profile_is_a_hard_dependency(self, process_app, monkeypatch, auth):
        monkeypatch.setattr(process_app, "system", StubClient(
            "system-api", HEALTHY_ROUTES,
            {"/api/v1/snowflake/customers/CRM-100005/360":
                DownstreamUnavailableError("warehouse down")}))
        client = TestClient(process_app.app, raise_server_exceptions=False)
        r = client.get("/api/v1/customers/CRM-100005/360", headers=auth)
        assert r.status_code == 503
        assert r.json()["retryable"] is True

    def test_ai_is_not_called_unless_requested(self, process_app, monkeypatch, auth):
        ai = StubClient("ai-service", {"/api/v1/customers": {"insights": [], "failures": []}})
        monkeypatch.setattr(process_app, "system", StubClient("system-api", HEALTHY_ROUTES))
        monkeypatch.setattr(process_app, "ai", ai)
        client = TestClient(process_app.app, raise_server_exceptions=False)
        client.get("/api/v1/customers/CRM-100005/360?includeAi=false", headers=auth)
        assert ai.calls == [], "a generative call must be opt-in per request"

    def test_idempotency_prevents_a_second_charged_call(self, process_app, monkeypatch, auth):
        ai = StubClient("ai-service", {"/api/v1/customers": {"insightId": "abc",
                                                             "generatedText": "x"}})
        monkeypatch.setattr(process_app, "ai", ai)
        client = TestClient(process_app.app, raise_server_exceptions=False)
        headers = {**auth, "Idempotency-Key": "unit-test-key"}
        first = client.post("/api/v1/customers/CRM-100005/ai-analysis",
                            json={"capability": "SUMMARY"}, headers=headers).json()
        second = client.post("/api/v1/customers/CRM-100005/ai-analysis",
                             json={"capability": "SUMMARY"}, headers=headers).json()
        assert first.get("idempotentReplay", False) is False
        assert second["idempotentReplay"] is True
        assert len(ai.calls) == 1, "the replay must not reach the model provider"


# ---------------------------------------------------------------------------
# Experience layer
# ---------------------------------------------------------------------------
PROCESS_RESPONSE = {
    "customerId": "CRM-100005",
    "profile": {"fullName": "Sofia Chen", "email": "sofia.chen@example.com",
                "phone": "+1-402-555-1005", "birthDate": "1960-04-17",
                "segment": "PREMIUM", "status": "ACTIVE", "tenureDays": 629},
    "orders": [{"orderId": "ORD-1"}], "support": [{"caseId": "CAS-1"}],
    "loyalty": {"tier": "BRONZE"}, "analytics": {"totalOrders": 15},
    "churnRisk": {"riskBand": "MEDIUM"}, "aiInsights": None,
    "dataQuality": {"completenessScore": 100,
                    "contributingSources": ["CRM", "OMS"], "asOf": "2026-08-28T04:15:02"},
    "partial": True,
    "degradedFields": [{"field": "loyalty", "dependency": "snowflake",
                        "errorCode": "PLATFORM:DOWNSTREAM_UNAVAILABLE",
                        "reason": "system-api returned HTTP 503."}],
    "correlationId": "test",
}


class TestExperienceLayer:
    @pytest.fixture()
    def client(self, experience_app, monkeypatch):
        monkeypatch.setattr(experience_app, "process",
                            StubClient("process-api", {"/api/v1/customers": PROCESS_RESPONSE}))
        return TestClient(experience_app.app, raise_server_exceptions=False)

    def test_identifiers_are_masked_without_the_pii_scope(self, client, auth):
        profile = client.get("/api/v1/customers/CRM-100005/360",
                             headers=auth).json()["profile"]
        assert profile["_masked"] is True
        assert "sofia.chen@example.com" not in str(profile)
        assert "Chen" not in str(profile)
        assert profile["fullName"].startswith("Sofia")

    def test_identifiers_are_returned_with_the_pii_scope(self, client, token_factory):
        # The service-desk client is entitled to pii:read; the portal client is
        # not. Same endpoint, same request, different answer - decided by the
        # token, never by a parameter the caller controls.
        token = token_factory("acme-servicedesk-client",
                              "customer:read insights:read pii:read")
        profile = client.get("/api/v1/customers/CRM-100005/360",
                             headers={"Authorization": f"Bearer {token}"}).json()["profile"]
        assert profile.get("_masked", False) is False
        assert profile["email"] == "sofia.chen@example.com"
        assert profile["fullName"] == "Sofia Chen"

    def test_the_same_request_differs_only_by_entitlement(self, client, token_factory):
        masked = client.get("/api/v1/customers/CRM-100005/360", headers={
            "Authorization":
                f"Bearer {token_factory('acme-portal-client', 'customer:read')}"}
        ).json()["profile"]
        unmasked = client.get("/api/v1/customers/CRM-100005/360", headers={
            "Authorization":
                f"Bearer {token_factory('acme-servicedesk-client', 'customer:read pii:read')}"}
        ).json()["profile"]
        assert masked["segment"] == unmasked["segment"]
        assert masked["email"] != unmasked["email"]

    def test_internal_dependency_names_do_not_leak_to_the_client(self, client, auth):
        meta = client.get("/api/v1/customers/CRM-100005/360", headers=auth).json()["meta"]
        assert meta["partial"] is True
        assert meta["degradedFields"] == ["loyalty"]
        assert "snowflake" not in str(meta).lower()
        assert "503" not in str(meta)

    def test_response_carries_provenance(self, client, auth):
        meta = client.get("/api/v1/customers/CRM-100005/360", headers=auth).json()["meta"]
        assert meta["dataCompletenessScore"] == 100
        assert meta["contributingSources"] == ["CRM", "OMS"]
        assert meta["asOf"]
        assert meta["correlationId"]

    def test_oauth_token_endpoint_issues_scoped_tokens(self, client):
        from common.config import get_settings
        r = client.post("/oauth/token", data={
            "grant_type": "client_credentials", "client_id": "acme-readonly-client",
            "client_secret": get_settings().oauth_client_secret})
        assert r.status_code == 200
        body = r.json()
        assert body["token_type"] == "Bearer"
        assert body["scope"] == "customer:read"

    def test_bad_client_secret_is_401(self, client):
        r = client.post("/oauth/token", data={
            "grant_type": "client_credentials", "client_id": "acme-portal-client",
            "client_secret": "wrong"})
        assert r.status_code == 401

    def test_unknown_client_is_indistinguishable_from_a_bad_secret(self, client):
        # No user enumeration: both answers are identical.
        bad_secret = client.post("/oauth/token", data={
            "grant_type": "client_credentials", "client_id": "acme-portal-client",
            "client_secret": "wrong"})
        unknown = client.post("/oauth/token", data={
            "grant_type": "client_credentials", "client_id": "no-such-client",
            "client_secret": "wrong"})
        assert bad_secret.status_code == unknown.status_code
        assert bad_secret.json()["message"] == unknown.json()["message"]

    def test_unsupported_grant_type_is_rejected(self, client):
        r = client.post("/oauth/token", data={
            "grant_type": "password", "client_id": "acme-portal-client",
            "client_secret": "x"})
        assert r.status_code == 400



# ---------------------------------------------------------------------------
# Store Associate Experience layer - the platform's second experience API
# ---------------------------------------------------------------------------
# Reuses PROCESS_RESPONSE from TestExperienceLayer above on purpose: if this
# consumer needed a different process-layer fixture to pass, "two consumers,
# one process API" would be a diagram, not a fact checked by this suite.
STORE_PROCESS_RESPONSE = {
    **PROCESS_RESPONSE,
    "orders": [
        {"orderId": "ORD-500", "orderDate": "2026-07-01", "orderStatus": "COMPLETED",
         "channel": "WEB", "currencyCode": "USD", "orderAmount": 220.0,
         "discountAmount": 20.0, "shippingAmount": 0.0, "netAmount": 200.0,
         "lineCount": 2, "totalUnits": 3},
    ],
}


class TestStoreAssociateExperienceLayer:
    @pytest.fixture()
    def client(self, store_app, monkeypatch):
        monkeypatch.setattr(store_app, "process",
                            StubClient("process-api",
                                      {"/api/v1/customers": STORE_PROCESS_RESPONSE}))
        return TestClient(store_app.app, raise_server_exceptions=False)

    def test_both_experience_apis_reuse_the_same_process_endpoint(
            self, store_app, experience_app, auth, monkeypatch):
        """The architectural claim, checked directly rather than trusted.

        Two independent stubs, one per experience API, each recording the
        calls it received. If a second consumer needed the process layer to
        expose something new, these two call logs would not be identical.
        """
        store_stub = StubClient("process-api", {"/api/v1/customers": PROCESS_RESPONSE})
        monkeypatch.setattr(store_app, "process", store_stub)
        TestClient(store_app.app, raise_server_exceptions=False).get(
            "/api/v1/associate/customers/CRM-100005/lookup", headers=auth)

        desk_stub = StubClient("process-api", {"/api/v1/customers": PROCESS_RESPONSE})
        monkeypatch.setattr(experience_app, "process", desk_stub)
        TestClient(experience_app.app, raise_server_exceptions=False).get(
            "/api/v1/customers/CRM-100005/360", headers=auth)

        assert store_stub.calls == desk_stub.calls == [
            ("GET", "/api/v1/customers/CRM-100005/360")]

    def test_lookup_omits_contact_fields_rather_than_masking_them(self, client, auth):
        """Stronger than masking: e-mail, phone and birth date are not in the
        shape at all, so there is nothing to leak by a masking bug."""
        body = client.get("/api/v1/associate/customers/CRM-100005/lookup",
                          headers=auth).json()
        assert "profile" not in body
        assert "email" not in body and "phone" not in body and "birthDate" not in body
        assert "sofia.chen@example.com" not in str(body)

    def test_display_name_is_masked(self, client, auth):
        body = client.get("/api/v1/associate/customers/CRM-100005/lookup",
                          headers=auth).json()
        assert body["displayName"].startswith("Sofia")
        assert "Chen" not in body["displayName"]
        assert body["meta"]["masked"] is True

    def test_the_narrow_store_scope_is_sufficient(self, client, token_factory):
        """The client actually registered for this app - customer:read only -
        must be enough. A test using a broader token would not prove that."""
        token = token_factory("acme-store-app-client", "customer:read")
        r = client.get("/api/v1/associate/customers/CRM-100005/lookup",
                       headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200

    def test_vip_flag_is_derived_from_segment(self, client, auth):
        # PROCESS_RESPONSE's profile.segment is PREMIUM.
        body = client.get("/api/v1/associate/customers/CRM-100005/lookup",
                          headers=auth).json()
        assert body["vip"] is True

    def test_degraded_dependency_is_named_not_hidden(self, client, auth):
        body = client.get("/api/v1/associate/customers/CRM-100005/lookup",
                          headers=auth).json()
        assert body["meta"]["partial"] is True
        assert body["meta"]["degradedFields"] == ["loyalty"]
        assert "snowflake" not in str(body["meta"]).lower()

    def test_recent_orders_reshapes_process_layer_field_names(self, store_app, auth,
                                                               monkeypatch):
        monkeypatch.setattr(store_app, "process",
                            StubClient("process-api",
                                      {"/api/v1/customers": STORE_PROCESS_RESPONSE}))
        client = TestClient(store_app.app, raise_server_exceptions=False)
        order = client.get("/api/v1/associate/customers/CRM-100005/recent-orders",
                           headers=auth).json()["orders"][0]
        # This consumer's vocabulary, not the process layer's.
        assert order["status"] == "COMPLETED"
        assert order["itemCount"] == 3
        assert "orderStatus" not in order and "totalUnits" not in order

    def test_health_exposes_circuit_breaker_state(self, client):
        body = client.get("/health").json()
        assert body["status"] == "UP"
        assert isinstance(body["circuitBreakers"], list)
