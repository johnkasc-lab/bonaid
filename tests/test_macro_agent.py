"""
tests/test_macro_agent.py
Tests the Macro Agent's regime classification (pure function, no network)
and graceful degradation when FRED isn't configured - the default state in
CI/this sandbox.
"""
from bonaid.agents.macro_agent import _classify_regime, _fetch_series, get_macro_snapshot


def test_classify_tightening_regime():
    regime, reasons = _classify_regime(fed_funds_change_3m=0.5, cpi_yoy=4.2)
    assert regime == "Tightening"
    assert any("risen" in r for r in reasons)
    assert any("elevated" in r for r in reasons)


def test_classify_easing_regime():
    regime, reasons = _classify_regime(fed_funds_change_3m=-0.75, cpi_yoy=1.2)
    assert regime == "Easing"
    assert any("fallen" in r for r in reasons)


def test_classify_neutral_regime():
    regime, reasons = _classify_regime(fed_funds_change_3m=0.02, cpi_yoy=2.1)
    assert regime == "Neutral"
    assert any("flat" in r for r in reasons)


def test_classify_boundary_at_positive_threshold():
    # 0.1 is the exact boundary - just above should be Tightening
    regime, _ = _classify_regime(fed_funds_change_3m=0.11, cpi_yoy=2.0)
    assert regime == "Tightening"


def test_classify_boundary_at_negative_threshold():
    regime, _ = _classify_regime(fed_funds_change_3m=-0.11, cpi_yoy=2.0)
    assert regime == "Easing"


def test_classify_no_data_when_fed_funds_missing():
    regime, reasons = _classify_regime(fed_funds_change_3m=None, cpi_yoy=2.0)
    assert regime == "No Data"


def test_fetch_series_returns_empty_without_api_key():
    # No FRED_API_KEY configured in test environment - must degrade
    # gracefully, not raise.
    result = _fetch_series("FEDFUNDS")
    assert result == []


def test_get_macro_snapshot_handles_missing_config_gracefully():
    snapshot = get_macro_snapshot()
    assert snapshot.regime == "No Data"
    assert len(snapshot.reasons) >= 1
