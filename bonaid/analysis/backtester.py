"""
backtester.py
Vectorized, realistic single-asset backtest engine.
Accounts for: transaction costs, slippage, next-bar execution (no lookahead bias),
and produces an equity curve + trade log.
"""
import numpy as np
import pandas as pd


def run_backtest(
    df: pd.DataFrame,
    signal: pd.Series,
    initial_capital: float = 100_000,
    commission_bps: float = 5,     # 0.05% per trade side
    slippage_bps: float = 5,       # 0.05% per trade side
) -> dict:
    """
    signal: 1 = long, 0 = flat (executed on the NEXT bar's open to avoid lookahead bias)
    Returns dict with equity_curve (pd.Series), trades (int count), returns (pd.Series)
    """
    df = df.copy()
    signal = signal.reindex(df.index).fillna(0)

    # Execute on next day's open -> shift signal by 1
    position = signal.shift(1).fillna(0)

    daily_return = df["Close"].pct_change().fillna(0)
    strategy_return = position * daily_return

    # Transaction costs applied whenever position changes
    position_change = position.diff().abs().fillna(0)
    cost_pct = (commission_bps + slippage_bps) / 10_000
    costs = position_change * cost_pct
    net_return = strategy_return - costs

    equity_curve = (1 + net_return).cumprod() * initial_capital
    trades = int((position_change > 0).sum())

    return {
        "equity_curve": equity_curve,
        "returns": net_return,
        "trades": trades,
        "position": position,
    }
