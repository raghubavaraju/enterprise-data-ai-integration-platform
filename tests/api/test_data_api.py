"""Snowflake SQL API (local implementation).

The tests that matter here are the safety ones.  This service is the only path
to the customer warehouse, so what it refuses is more important than what it
returns.
"""
from __future__ import annotations

import pytest


def statement(client, token, sql, bindings=None, **extra):
    return client.post("/api/v2/statements",
                       json={"statement": sql, "bindings": bindings or {}, **extra},
                       headers={"Authorization": f"Bearer {token}"})


class TestStatementGuardrails:
    @pytest.mark.parametrize("sql", [
        "INSERT INTO ACME_EDP.CORE.CUSTOMER (CUSTOMER_BK) VALUES ('x')",
        "UPDATE ACME_EDP.CORE.CUSTOMER SET EMAIL = 'x'",
        "DELETE FROM ACME_EDP.CORE.CUSTOMER",
        "DROP TABLE ACME_EDP.CORE.CUSTOMER",
        "CREATE TABLE evil (a INT)",
        "GRANT SELECT ON ALL TABLES IN SCHEMA CORE TO ROLE PUBLIC",
        "TRUNCATE TABLE ACME_EDP.CORE.CUSTOMER",
    ])
    def test_mutating_statements_are_refused(self, data_api_client, full_token, sql):
        # Second line of defence. The Snowflake role is read-only in production,
        # but a control that exists in only one place is a single point of
        # failure - and RBAC is the one most likely to be mis-granted.
        r = statement(data_api_client, full_token, sql)
        assert r.status_code == 400
        assert r.json()["errorCode"] == "PLATFORM:VALIDATION_ERROR"

    def test_statement_batching_is_refused(self, data_api_client, full_token):
        # "SELECT 1; DROP TABLE ..." is the classic way past a naive prefix check.
        r = statement(data_api_client, full_token,
                      "SELECT 1; DELETE FROM ACME_EDP.CORE.CUSTOMER")
        assert r.status_code == 400

    def test_a_select_is_accepted(self, data_api_client, full_token):
        r = statement(data_api_client, full_token,
                      "SELECT COUNT(*) AS N FROM ACME_EDP.ANALYTICS.CUSTOMER_360")
        assert r.status_code == 200
        assert int(r.json()["data"][0][0]) > 0

    def test_a_cte_is_accepted(self, data_api_client, full_token):
        r = statement(data_api_client, full_token,
                      "WITH t AS (SELECT 1 AS A) SELECT A FROM t")
        assert r.status_code == 200


class TestBindings:
    def test_bind_parameters_are_used(self, data_api_client, full_token, known_customer):
        r = statement(data_api_client, full_token,
                      "SELECT CUSTOMER_ID FROM ACME_EDP.ANALYTICS.V_CUSTOMER_360_API "
                      "WHERE CUSTOMER_ID = ?",
                      {"1": {"type": "TEXT", "value": known_customer}})
        assert r.status_code == 200
        assert r.json()["data"][0][0] == known_customer

    def test_injection_through_a_bind_value_is_inert(self, data_api_client, full_token):
        # The value is data, not SQL: the query simply matches nothing.
        r = statement(data_api_client, full_token,
                      "SELECT CUSTOMER_ID FROM ACME_EDP.ANALYTICS.V_CUSTOMER_360_API "
                      "WHERE CUSTOMER_ID = ?",
                      {"1": {"type": "TEXT", "value": "x' OR '1'='1"}})
        assert r.status_code == 200
        assert r.json()["resultSetMetaData"]["numRows"] == 0


class TestResponseEnvelope:
    def test_shape_mirrors_the_snowflake_sql_api(self, data_api_client, full_token):
        # Deliberate: the DataWeave that parses this response is the same in
        # local and cloud mode.
        body = statement(data_api_client, full_token,
                         "SELECT 1 AS N, 'a' AS S, TRUE AS B").json()
        assert set(body) >= {"resultSetMetaData", "data", "code", "statementHandle"}
        assert [c["name"] for c in body["resultSetMetaData"]["rowType"]] == ["N", "S", "B"]
        assert all(isinstance(v, str) for v in body["data"][0])

    def test_numeric_and_boolean_types_are_declared(self, data_api_client, full_token):
        body = statement(data_api_client, full_token,
                         "SELECT 1 AS I, 1.5 AS F, TRUE AS B, 'x' AS S").json()
        types = {c["name"]: c["type"] for c in body["resultSetMetaData"]["rowType"]}
        assert types["I"] == "FIXED"
        assert types["F"] == "REAL"
        assert types["B"] == "BOOLEAN"
        assert types["S"] == "TEXT"

    def test_a_broken_statement_becomes_a_data_platform_error(self, data_api_client, full_token):
        r = statement(data_api_client, full_token, "SELECT * FROM ACME_EDP.NOPE.MISSING")
        assert r.status_code == 502
        body = r.json()
        assert body["errorCode"] == "DATA:QUERY_FAILED"
        assert body["retryable"] is True


class TestAsyncExecution:
    def test_async_submission_returns_a_handle_that_can_be_polled(self, data_api_client, full_token):
        submitted = statement(data_api_client, full_token,
                              "SELECT COUNT(*) AS N FROM ACME_EDP.CORE.SALES_ORDER",
                              **{"async": True}).json()
        handle = submitted["statementHandle"]
        polled = data_api_client.get(f"/api/v2/statements/{handle}",
                                     headers={"Authorization": f"Bearer {full_token}"})
        assert polled.status_code == 200
        assert int(polled.json()["data"][0][0]) > 0

    def test_unknown_handle_is_rejected(self, data_api_client, full_token):
        r = data_api_client.get("/api/v2/statements/does-not-exist",
                                headers={"Authorization": f"Bearer {full_token}"})
        assert r.status_code == 400


class TestInternalWrites:
    def test_write_requires_the_ai_write_scope(self, data_api_client, full_token):
        # acme-portal-client holds ai:invoke but NOT ai:write. Only the AI
        # service itself may persist an insight.
        r = data_api_client.post("/internal/v1/writes/ai_audit", json={"rows": [[]]},
                                 headers={"Authorization": f"Bearer {full_token}"})
        assert r.status_code == 403

    def test_unknown_write_operation_is_refused(self, data_api_client, token_factory):
        token = token_factory("acme-ai-service", "ai:write")
        r = data_api_client.post("/internal/v1/writes/drop_everything",
                                 json={"rows": [["x"]]},
                                 headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 400
        assert "not an approved write operation" in r.json()["message"]


class TestOperations:
    def test_health_checks_the_warehouse(self, data_api_client):
        assert data_api_client.get("/health").json()["status"] == "UP"

    def test_correlation_id_is_echoed(self, data_api_client, full_token):
        r = statement(data_api_client, full_token, "SELECT 1")
        assert r.headers["x-correlation-id"]
