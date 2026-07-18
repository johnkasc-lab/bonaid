"""
tests/test_paper_trading.py
Tests the Paper Trading engine's pure decision logic - no DB needed.
"""
from bonaid.agents.paper_trading import should_close_position, compute_pnl


def test_stop_loss_triggers_close():
    check = should_close_position(current_price=94.0, stop_loss=95.0, take_profit=110.0)
    assert check.should_close is True
    assert check.reason == "stop_loss"


def test_take_profit_triggers_close():
    check = should_close_position(current_price=112.0, stop_loss=95.0, take_profit=110.0)
    assert check.should_close is True
    assert check.reason == "take_profit"


def test_price_between_levels_holds():
    check = should_close_position(current_price=100.0, stop_loss=95.0, take_profit=110.0)
    assert check.should_close is False
    assert check.reason is None


def test_price_gap_through_both_levels_favors_stop_loss():
    # Conservative assumption: if a gap somehow crosses both levels at
    # once, treat it as the stop being hit - protecting capital over
    # capturing the extra gain.
    check = should_close_position(current_price=93.0, stop_loss=95.0, take_profit=94.0)
    assert check.reason == "stop_loss"


def test_exact_stop_price_triggers_close():
    check = should_close_position(current_price=95.0, stop_loss=95.0, take_profit=110.0)
    assert check.should_close is True
    assert check.reason == "stop_loss"


def test_compute_pnl_profit():
    assert compute_pnl(entry_price=100, exit_price=110, shares=50) == 500


def test_compute_pnl_loss():
    assert compute_pnl(entry_price=100, exit_price=95, shares=50) == -250


def test_compute_pnl_flat():
    assert compute_pnl(entry_price=100, exit_price=100, shares=50) == 0


# --- evaluate_portfolio_drawdown: the portfolio-level check that individual
# per-position stop-losses don't catch ---
from bonaid.agents.paper_trading import evaluate_portfolio_drawdown


def test_drawdown_not_breached_on_small_loss():
    positions = [{"ticker": "AAPL", "shares": 40, "entry_price": 200.0, "current_price": 195.0}]  # -$200, -0.2%
    result = evaluate_portfolio_drawdown(positions, capital=100_000, max_drawdown_pct=15.0)
    assert result["breached"] is False


def test_drawdown_breached_on_large_loss():
    positions = [
        {"ticker": "AAPL", "shares": 400, "entry_price": 200.0, "current_price": 150.0},  # -$20,000
        {"ticker": "MSFT", "shares": 200, "entry_price": 400.0, "current_price": 350.0},  # -$10,000
    ]
    result = evaluate_portfolio_drawdown(positions, capital=100_000, max_drawdown_pct=15.0)
    assert result["breached"] is True
    assert result["drawdown_pct"] == -30.0


def test_drawdown_never_breaches_on_profit():
    positions = [{"ticker": "AAPL", "shares": 40, "entry_price": 180.0, "current_price": 250.0}]
    result = evaluate_portfolio_drawdown(positions, capital=100_000, max_drawdown_pct=15.0)
    assert result["breached"] is False
    assert result["total_unrealized_pnl"] > 0


def test_drawdown_empty_positions_never_breaches():
    result = evaluate_portfolio_drawdown([], capital=100_000, max_drawdown_pct=15.0)
    assert result["breached"] is False
    assert result["total_unrealized_pnl"] == 0.0


def test_drawdown_exactly_at_threshold_breaches():
    # -15% exactly should breach (>= threshold, not strictly >)
    positions = [{"ticker": "AAPL", "shares": 100, "entry_price": 200.0, "current_price": 170.0}]  # -$3000 on 20000 capital = -15%
    result = evaluate_portfolio_drawdown(positions, capital=20_000, max_drawdown_pct=15.0)
    assert result["breached"] is True
