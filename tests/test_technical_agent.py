"""
tests/test_technical_agent.py
Tests the Technical Agent's core aggregation logic in isolation (no DB, no
LLM, no live data needed) using the synthetic data generator.
"""
from bonaid.analysis.synthetic_data import generate_universe
from bonaid.agents.technical_agent import analyze_ticker


def test_analyze_ticker_returns_valid_action():
    data = generate_universe(["TEST"], years=5)
    result = analyze_ticker("TEST", data["TEST"])

    assert result.ticker == "TEST"
    assert result.action in {"BUY", "SELL", "HOLD", "WATCH"}
    assert 0.0 <= result.confidence <= 100.0
    assert len(result.reasons) >= 1
    assert len(result.signal_breakdown) > 0


def test_analyze_ticker_breakdown_has_expected_fields():
    data = generate_universe(["TEST2"], years=5)
    result = analyze_ticker("TEST2", data["TEST2"])

    for entry in result.signal_breakdown:
        assert "strategy" in entry
        assert "signal" in entry
        assert entry["signal"] in {"LONG", "FLAT", "ERROR"}
