"""
tests/test_foundation.py
Phase 1 tests - deliberately independent of live Postgres/Redis/Ollama so
they run anywhere (including CI) without docker-compose up. Integration
tests against real services belong in tests/test_integration.py (added
once Phase 2+ needs it).
"""
from bonaid.config import settings
from bonaid.graph import run_ping, build_graph


def test_settings_load():
    assert settings.app_name == "Bonaid"
    assert settings.postgres_url.startswith("postgresql+psycopg2://")
    assert settings.redis_url.startswith("redis://")


def test_graph_builds():
    app = build_graph()
    assert app is not None


def test_graph_ping():
    result = run_ping(query="unit test", ticker="TEST")
    assert "alive" in result
    assert "TEST" in result


def test_models_import_cleanly():
    from bonaid.models import ScanLog, SystemHealth
    assert ScanLog.__tablename__ == "scan_log"
    assert SystemHealth.__tablename__ == "system_health"
