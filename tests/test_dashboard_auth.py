"""
tests/test_dashboard_auth.py
Tests the dashboard's HTTP Basic Auth gate. Uses monkeypatch to toggle
settings.dashboard_username/password per test, rather than os.environ,
since the settings object is a module-level singleton already instantiated
by the time tests run - monkeypatching the object's attributes directly is
the safe way to change it per-test without leaking state into other test
files that import the same shared `settings`.
"""
from fastapi.testclient import TestClient
from bonaid.dashboard.main import app
from bonaid.config import settings

client = TestClient(app, raise_server_exceptions=False)


def test_auth_disabled_by_default(monkeypatch):
    monkeypatch.setattr(settings, "dashboard_username", None)
    monkeypatch.setattr(settings, "dashboard_password", None)
    r = client.get("/api/status")
    assert r.status_code == 200  # no auth required when unconfigured


def test_auth_rejects_missing_credentials(monkeypatch):
    monkeypatch.setattr(settings, "dashboard_username", "admin")
    monkeypatch.setattr(settings, "dashboard_password", "secret")
    r = client.get("/api/status")
    assert r.status_code == 401


def test_auth_rejects_wrong_credentials(monkeypatch):
    monkeypatch.setattr(settings, "dashboard_username", "admin")
    monkeypatch.setattr(settings, "dashboard_password", "secret")
    r = client.get("/api/status", auth=("wrong", "wrong"))
    assert r.status_code == 401


def test_auth_accepts_correct_credentials(monkeypatch):
    monkeypatch.setattr(settings, "dashboard_username", "admin")
    monkeypatch.setattr(settings, "dashboard_password", "secret")
    r = client.get("/api/status", auth=("admin", "secret"))
    assert r.status_code == 200


def test_auth_applies_to_all_routes_not_just_status(monkeypatch):
    monkeypatch.setattr(settings, "dashboard_username", "admin")
    monkeypatch.setattr(settings, "dashboard_password", "secret")
    for path in ["/api/positions", "/api/portfolio", "/api/pnl", "/api/analytics", "/api/macro", "/api/drawdown", "/api/decisions"]:
        r = client.get(path)
        assert r.status_code == 401, f"{path} was not protected by auth"
