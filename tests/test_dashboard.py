"""
tests/test_dashboard.py
Tests the dashboard's error-handling behavior when Postgres/Redis aren't
reachable - the default state in this sandbox/CI. The real point of these
tests: no endpoint should ever raise an unhandled exception up to a real
HTTP response - everything must degrade to a clean, informative error.
"""
from fastapi.testclient import TestClient
from bonaid.dashboard.main import app

client = TestClient(app, raise_server_exceptions=False)


def test_index_serves_html():
    r = client.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]


def test_status_endpoint_never_crashes():
    r = client.get("/api/status")
    assert r.status_code == 200
    body = r.json()
    assert "checks" in body
    assert "postgres" in body["checks"]
    assert "redis" in body["checks"]


def test_macro_endpoint_degrades_without_fred_key():
    r = client.get("/api/macro")
    assert r.status_code == 200
    assert r.json()["regime"] == "No Data"


def test_db_dependent_endpoints_return_clean_error_not_crash():
    # No Postgres in this test environment - every one of these should
    # come back as a clean 503 with an 'error' field, never an unhandled
    # exception reaching the HTTP layer.
    for path in ["/api/pnl", "/api/positions", "/api/portfolio", "/api/decisions"]:
        r = client.get(path)
        assert r.status_code == 503, f"{path} did not degrade cleanly"
        assert "error" in r.json()


def test_drawdown_endpoint_returns_clean_error_without_db():
    r = client.get("/api/drawdown")
    assert r.status_code == 503
    assert "error" in r.json()
