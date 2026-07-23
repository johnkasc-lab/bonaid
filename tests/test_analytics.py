"""
tests/test_analytics.py
Tests bonaid/analytics.py's pure functions - equity curve construction,
track-record metrics, and per-agent attribution. No DB needed.
"""
from datetime import datetime, timedelta, timezone
from bonaid.analytics import (
    build_equity_curve, compute_track_record_metrics,
    attribute_by_override, attribute_by_driving_strategy,
    MIN_TRADES_FOR_SHARPE,
)

NOW = datetime.now(timezone.utc)


def _trade(ticker, days_ago, pnl):
    return {"ticker": ticker, "exit_date": NOW - timedelta(days=days_ago), "realized_pnl": pnl}


def test_equity_curve_accumulates_correctly():
    trades = [_trade("A", 3, 500), _trade("B", 2, -200), _trade("C", 1, 300)]
    curve = build_equity_curve(trades, starting_capital=100_000)
    assert [p.equity for p in curve] == [100500.0, 100300.0, 100600.0]


def test_equity_curve_sorts_by_exit_date_regardless_of_input_order():
    # Deliberately out of order input
    trades = [_trade("C", 1, 300), _trade("A", 3, 500), _trade("B", 2, -200)]
    curve = build_equity_curve(trades, starting_capital=100_000)
    assert [p.ticker for p in curve] == ["A", "B", "C"]


def test_max_drawdown_computed_correctly():
    trades = [_trade("A", 3, 500), _trade("B", 2, -400), _trade("C", 1, 100)]
    metrics = compute_track_record_metrics(trades, starting_capital=100_000)
    # Peak after A = 100500, trough after B = 100100 -> drawdown = -400/100500
    expected_dd = round((100100 - 100500) / 100500 * 100, 2)
    assert metrics.max_drawdown_pct == expected_dd


def test_win_rate_and_profit_factor():
    trades = [_trade("A", 3, 500), _trade("B", 2, -100), _trade("C", 1, 300)]
    metrics = compute_track_record_metrics(trades, starting_capital=100_000)
    assert metrics.win_rate == round(2 / 3 * 100, 1)
    assert metrics.profit_factor == round(800 / 100, 2)


def test_sharpe_suppressed_below_minimum_trades():
    trades = [_trade(f"T{i}", i, 100) for i in range(MIN_TRADES_FOR_SHARPE - 1)]
    metrics = compute_track_record_metrics(trades, starting_capital=100_000)
    assert metrics.sharpe_approx is None
    assert any("suppressed" in n for n in metrics.notes)


def test_sharpe_computed_at_minimum_trades():
    trades = [_trade(f"T{i}", i, 100 if i % 2 == 0 else -50) for i in range(MIN_TRADES_FOR_SHARPE)]
    metrics = compute_track_record_metrics(trades, starting_capital=100_000)
    assert metrics.sharpe_approx is not None


def test_empty_trades_returns_zeroed_track_record():
    metrics = compute_track_record_metrics([], starting_capital=100_000)
    assert metrics.trade_count == 0
    assert metrics.total_return_pct == 0.0
    assert "No closed trades" in metrics.notes[0]


def test_profit_factor_undefined_with_no_losses():
    trades = [_trade("A", 1, 500)]
    metrics = compute_track_record_metrics(trades, starting_capital=100_000)
    assert metrics.profit_factor is None


def test_attribute_by_override_separates_groups_correctly():
    trades = [
        {"realized_pnl": 500, "overridden": True},
        {"realized_pnl": -100, "overridden": True},
        {"realized_pnl": 300, "overridden": False},
    ]
    result = attribute_by_override(trades)
    assert result["overridden"]["trade_count"] == 2
    assert result["not_overridden"]["trade_count"] == 1
    assert result["not_overridden"]["win_rate"] == 100.0


def test_attribute_by_override_flags_small_sample_as_unreliable():
    trades = [{"realized_pnl": 100, "overridden": True}]
    result = attribute_by_override(trades)
    assert result["reliable"] is False


def test_attribute_by_driving_strategy_picks_highest_sharpe_entry():
    trades = [
        {
            "realized_pnl": 500,
            "signal_breakdown": [
                {"strategy": "RSI_MeanReversion", "sharpe_5y": 0.3},
                {"strategy": "MACD_Trend", "sharpe_5y": 0.9},  # highest - should be attributed here
            ],
        },
    ]
    result = attribute_by_driving_strategy(trades)
    assert "MACD_Trend" in result
    assert "RSI_MeanReversion" not in result
    assert result["MACD_Trend"]["avg_pnl"] == 500


def test_attribute_by_driving_strategy_handles_missing_breakdown_gracefully():
    trades = [{"realized_pnl": 100, "signal_breakdown": None}]
    result = attribute_by_driving_strategy(trades)
    assert result == {}
