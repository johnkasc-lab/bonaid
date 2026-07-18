"""
tests/test_portfolio_agent.py
Tests the Portfolio Agent's pure aggregation logic - no DB needed, takes
already-fetched decision dicts, same pattern as Supervisor's tests.
"""
from datetime import datetime, timedelta, timezone
from bonaid.agents.portfolio_agent import build_snapshot_from_decisions

NOW = datetime.now(timezone.utc)


def _decision(ticker, action, confidence, hours_ago=0, tradeable=False, shares=0, value=0.0, pct=0.0):
    return {
        "ticker": ticker,
        "action": action,
        "confidence": confidence,
        "timestamp": NOW - timedelta(hours=hours_ago),
        "risk_assessment": {
            "tradeable": tradeable,
            "position_shares": shares,
            "position_value": value,
            "position_pct_of_capital": pct,
        },
    }


def test_only_latest_decision_per_ticker_counts():
    decisions = [
        _decision("AAPL", "BUY", 80, hours_ago=2, tradeable=True, shares=50, value=9000, pct=9.0),
        _decision("AAPL", "WATCH", 50, hours_ago=1, tradeable=False),  # supersedes the BUY above
    ]
    snap = build_snapshot_from_decisions(decisions, capital=100_000)
    assert snap.position_count == 0  # latest AAPL decision was WATCH, no position


def test_sized_buy_counted_as_open_position():
    decisions = [_decision("MSFT", "BUY", 75, tradeable=True, shares=20, value=8000, pct=8.0)]
    snap = build_snapshot_from_decisions(decisions, capital=100_000)
    assert snap.position_count == 1
    assert snap.deployed_capital == 8000
    assert snap.positions[0].ticker == "MSFT"


def test_non_buy_actions_never_counted():
    decisions = [
        _decision("AAPL", "WATCH", 50),
        _decision("MSFT", "HOLD", 30),
        _decision("TSLA", "SELL", 10),
    ]
    snap = build_snapshot_from_decisions(decisions, capital=100_000)
    assert snap.position_count == 0
    assert snap.deployed_capital == 0.0


def test_total_exposure_warning_triggers_above_threshold():
    decisions = [
        _decision("AAPL", "BUY", 80, tradeable=True, shares=50, value=30_000, pct=30.0),
        _decision("MSFT", "BUY", 75, tradeable=True, shares=20, value=30_000, pct=30.0),
    ]
    snap = build_snapshot_from_decisions(decisions, capital=100_000, max_total_exposure_pct=50.0)
    assert snap.deployed_pct == 60.0
    assert any("exceeds" in w for w in snap.warnings)


def test_no_warning_when_under_threshold():
    decisions = [_decision("AAPL", "BUY", 80, tradeable=True, shares=10, value=5000, pct=5.0)]
    snap = build_snapshot_from_decisions(decisions, capital=100_000, max_total_exposure_pct=50.0)
    assert not any("exceeds" in w for w in snap.warnings)


def test_empty_decisions_flagged():
    snap = build_snapshot_from_decisions([], capital=100_000)
    assert snap.position_count == 0
    assert any("No open positions" in w for w in snap.warnings)


def test_positions_sorted_by_value_descending():
    decisions = [
        _decision("SMALL", "BUY", 60, tradeable=True, shares=5, value=1000, pct=1.0),
        _decision("BIG", "BUY", 90, tradeable=True, shares=100, value=20000, pct=20.0),
    ]
    snap = build_snapshot_from_decisions(decisions, capital=100_000)
    assert snap.positions[0].ticker == "BIG"
    assert snap.positions[1].ticker == "SMALL"


# --- build_snapshot_from_positions: the real-position-based function used
# now that Paper Trading exists (build_snapshot_from_decisions above is the
# legacy pre-Paper-Trading version, kept for reference/backward compat) ---
from bonaid.agents.portfolio_agent import build_snapshot_from_positions


def test_positions_snapshot_computes_value_correctly():
    positions = [{"ticker": "SPY", "shares": 13, "entry_price": 754.81, "entry_confidence": 78.3}]
    snap = build_snapshot_from_positions(positions, capital=100_000)
    assert snap.deployed_capital == round(13 * 754.81, 2)
    assert snap.positions[0].confidence == 78.3


def test_positions_snapshot_defaults_confidence_when_missing():
    # Regression test: entry_confidence used to be hardcoded to 0.0 for
    # every position regardless of what was actually stored. Now it should
    # reflect the real value when present, and default gracefully (not
    # crash) when a position dict doesn't include the key at all.
    positions = [{"ticker": "AAPL", "shares": 10, "entry_price": 180.0}]
    snap = build_snapshot_from_positions(positions, capital=100_000)
    assert snap.positions[0].confidence == 0.0
