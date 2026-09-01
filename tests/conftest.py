"""Shared pytest fixtures.

Design decision: the API tests run the FastAPI applications **in-process** with
``TestClient`` rather than against a running stack.  That means the suite needs
no docker, no ports and no sleep-and-retry, and a failure points at code rather
than at the environment.  The trade-off is that inter-service HTTP is stubbed;
the really cross-process behaviour is covered by ``tests/integration``, which
is skipped automatically when the stack is not up.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO_ROOT), str(REPO_ROOT / "services")]

# Tests always talk to the warehouse directly: the point of a test is to be
# hermetic, and routing through the SQL API service would make every test
# depend on a second process being alive.
os.environ.setdefault("WAREHOUSE_ACCESS", "direct")
# The suite builds and owns its own warehouse file. DuckDB allows one read-write
# process, so sharing the development database would make the tests fail
# whenever the local stack happened to be running - the classic "works on my
# machine, red in CI" failure, inverted.
os.environ.setdefault("LOCAL_WAREHOUSE_PATH", "local_warehouse/test_acme_edp.duckdb")
os.environ.setdefault("PLATFORM_MODE", "local")
os.environ.setdefault("AI_PROVIDER", "local")
os.environ.setdefault("LOG_FORMAT", "plain")


@pytest.fixture(scope="session", autouse=True)
def warehouse():
    """Build the test warehouse once per session, from scratch.

    Rebuilding and not reusing is deliberate: a test suite that depends on
    the state left behind by the last run is a test suite that passes for the
    wrong reason. The build takes a few seconds and runs once.
    """
    from local_warehouse.build import build
    assert build() == 0, "local warehouse build failed"
    from local_warehouse.warehouse import shared
    return shared()


@pytest.fixture(scope="session")
def token_factory():
    from common.config import get_settings
    from common.security import issue_token
    secret = get_settings().oauth_client_secret

    def _issue(client_id: str = "acme-portal-client", scope: str | None = None) -> str:
        return issue_token(client_id, secret, scope)["access_token"]

    return _issue


@pytest.fixture(scope="session")
def full_token(token_factory):
    return token_factory("acme-portal-client", "customer:read insights:read ai:invoke")


@pytest.fixture(scope="session")
def readonly_token(token_factory):
    return token_factory("acme-readonly-client", "customer:read")


@pytest.fixture()
def auth(full_token):
    return {"Authorization": f"Bearer {full_token}"}


@pytest.fixture(scope="session")
def known_customer(warehouse) -> str:
    """A customer that exists in every rebuild of the sample dataset."""
    row = warehouse.execute(
        "SELECT CUSTOMER_BK FROM ACME_EDP.ANALYTICS.CUSTOMER_360 "
        "WHERE TOTAL_ORDERS > 0 AND TOTAL_CASES > 0 ORDER BY CUSTOMER_BK LIMIT 1").fetchone()
    assert row, "the sample dataset must contain at least one customer with orders and cases"
    return row[0]


@pytest.fixture(scope="session")
def at_risk_customer(warehouse) -> str:
    row = warehouse.execute(
        "SELECT CUSTOMER_BK FROM ACME_EDP.AI.CUSTOMER_CHURN_SCORE "
        "ORDER BY CHURN_PROBABILITY DESC LIMIT 1").fetchone()
    assert row, "the sample dataset must produce at least one churn score"
    return row[0]


@pytest.fixture()
def ai_client():
    from fastapi.testclient import TestClient

    from ai_service.app import app
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture()
def data_api_client():
    from fastapi.testclient import TestClient

    from data_api.app import app
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture()
def crm_client():
    from fastapi.testclient import TestClient

    from mock_services.crm.app import app
    return TestClient(app, raise_server_exceptions=False)
