"""Mock source systems.

Small suite, but it earns its place: these fixtures are what every other test
and the whole local demo stand on.  If the CRM mock stops returning the quirks
it is supposed to model, the System API layer stops being tested against
anything realistic.
"""
from __future__ import annotations

import pytest


class TestCrm:
    def test_returns_a_customer_by_business_key(self, crm_client, known_customer):
        r = crm_client.get(f"/api/v1/customers/{known_customer}")
        assert r.status_code == 200
        assert r.json()["customerId"] == known_customer

    def test_unknown_customer_is_404(self, crm_client):
        assert crm_client.get("/api/v1/customers/CRM-000000").status_code == 404

    def test_addresses_return_an_empty_list_for_an_unknown_customer(self, crm_client):
        # The quirk the CRM System API exists to absorb: 200 + [] is
        # indistinguishable from "no addresses" without a second call.
        r = crm_client.get("/api/v1/customers/CRM-000000/addresses")
        assert r.status_code == 200
        assert r.json() == []

    def test_pagination_is_bounded(self, crm_client):
        assert crm_client.get("/api/v1/customers", params={"limit": 1000}).status_code == 422
        body = crm_client.get("/api/v1/customers", params={"limit": 5}).json()
        assert len(body["data"]) == 5
        assert body["pagination"]["hasMore"] is True

    def test_incremental_filter_is_supported(self, crm_client):
        # The mechanism behind watermark-based incremental ingestion.
        all_rows = crm_client.get("/api/v1/customers", params={"limit": 500}).json()
        future = crm_client.get("/api/v1/customers",
                                params={"limit": 500, "updatedSince": "2099-01-01"}).json()
        assert all_rows["pagination"]["total"] > 0
        assert future["pagination"]["total"] == 0

    def test_records_with_a_null_business_key_are_not_served(self, crm_client):
        # The planted defect exists in the file, but a source system would not
        # serve an unkeyed record over its API - it arrives via the bulk export.
        rows = crm_client.get("/api/v1/customers", params={"limit": 500}).json()["data"]
        assert all(r["customerId"] for r in rows)


class TestFaultInjection:
    def test_error_fault_returns_500(self, crm_client, known_customer):
        r = crm_client.get(f"/api/v1/customers/{known_customer}", params={"__fault": "error"})
        assert r.status_code == 500

    def test_throttle_fault_returns_429(self, crm_client, known_customer):
        r = crm_client.get(f"/api/v1/customers/{known_customer}", params={"__fault": "throttle"})
        assert r.status_code == 429

    def test_no_fault_by_default(self, crm_client, known_customer):
        assert crm_client.get(f"/api/v1/customers/{known_customer}").status_code == 200


@pytest.fixture()
def orders_client():
    from fastapi.testclient import TestClient

    from mock_services.orders.app import app
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture()
def support_client():
    from fastapi.testclient import TestClient

    from mock_services.support.app import app
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture()
def loyalty_client():
    from fastapi.testclient import TestClient

    from mock_services.loyalty.app import app
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture()
def catalog_client():
    from fastapi.testclient import TestClient

    from mock_services.catalog.app import app
    return TestClient(app, raise_server_exceptions=False)


class TestOrderManagement:
    def test_orders_are_filtered_by_customer(self, orders_client, known_customer):
        body = orders_client.get("/api/v1/orders",
                                 params={"customerId": known_customer}).json()
        assert body["pagination"]["total"] > 0
        assert all(o["customerId"] == known_customer for o in body["data"])

    def test_orders_are_returned_newest_first(self, orders_client, known_customer):
        dates = [o["orderDate"] for o in orders_client.get(
            "/api/v1/orders", params={"customerId": known_customer}).json()["data"]]
        assert dates == sorted(dates, reverse=True)

    def test_order_lines_are_a_separate_resource(self, orders_client, known_customer):
        # The OMS never embeds lines; the System API is what hides that from
        # consumers who only want a total.
        order = orders_client.get("/api/v1/orders",
                                  params={"customerId": known_customer}).json()["data"][0]
        assert "lines" not in order
        lines = orders_client.get(f"/api/v1/orders/{order['orderId']}/lines").json()
        assert lines and lines[0]["orderId"] == order["orderId"]

    def test_unknown_order_is_404(self, orders_client):
        assert orders_client.get("/api/v1/orders/ORD-000000").status_code == 404


class TestSupport:
    def test_cases_are_filtered_by_customer_and_status(self, support_client, known_customer):
        body = support_client.get("/api/v1/cases",
                                  params={"customerId": known_customer,
                                          "status": "resolved"}).json()
        assert all(c["status"] == "RESOLVED" for c in body["data"])

    def test_knowledge_articles_carry_their_metadata(self, support_client):
        # These are the RAG corpus. Without an article id and an owner, a cited
        # answer cannot be traced back to a governed source.
        articles = support_client.get("/api/v1/knowledge-articles").json()
        assert len(articles) >= 10
        for a in articles:
            assert a["articleId"].startswith("KB-")
            assert a["owner"] and a["category"] and a["sourceUri"]
            assert a["content"].strip()


class TestLoyalty:
    def test_enrolled_customer_has_an_account(self, loyalty_client, warehouse):
        row = warehouse.execute(
            "SELECT CUSTOMER_BK FROM ACME_EDP.CORE.LOYALTY_ACCOUNT LIMIT 1").fetchone()
        r = loyalty_client.get(f"/api/v1/loyalty-accounts/by-customer/{row[0]}")
        assert r.status_code == 200
        assert r.json()["tier"] in ("BRONZE", "SILVER", "GOLD", "PLATINUM")

    def test_unenrolled_customer_is_404_at_the_source(self, loyalty_client, warehouse):
        # The ambiguity the CRM System API translates away - see
        # tests/api/test_gateway_layers.py::TestSystemLayer.
        row = warehouse.execute("""
            SELECT c.CUSTOMER_BK FROM ACME_EDP.CORE.CUSTOMER c
            WHERE NOT EXISTS (SELECT 1 FROM ACME_EDP.CORE.LOYALTY_ACCOUNT l
                               WHERE l.CUSTOMER_BK = c.CUSTOMER_BK) LIMIT 1""").fetchone()
        assert row, "the sample dataset must contain an unenrolled customer"
        assert loyalty_client.get(
            f"/api/v1/loyalty-accounts/by-customer/{row[0]}").status_code == 404


class TestCatalog:
    def test_products_can_be_filtered_by_category(self, catalog_client):
        body = catalog_client.get("/api/v1/products", params={"category": "Coffee"}).json()
        assert body["data"] and all(p["category"] == "Coffee" for p in body["data"])

    def test_unknown_product_is_404(self, catalog_client):
        assert catalog_client.get("/api/v1/products/PRD-9999").status_code == 404
