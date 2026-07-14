"""
metrics.py
Standard institutional performance metrics computed off a daily returns series
and/or an equity curve.
"""
import numpy as np
import pandas as pd

TRADING_DAYS = 252


def cagr(equity_curve: pd.Series) -> float:
    n_years = len(equity_curve) / TRADING_DAYS
    if n_years <= 0 or equity_curve.iloc[0] <= 0:
        return np.nan
    return (equity_curve.iloc[-1] / equity_curve.iloc[0]) ** (1 / n_years) - 1


def sharpe_ratio(returns: pd.Series, risk_free: float = 0.0) -> float:
    excess = returns - risk_free / TRADING_DAYS
    std = excess.std()
    if std == 0 or np.isnan(std):
        return 0.0
    return (excess.mean() / std) * np.sqrt(TRADING_DAYS)


def sortino_ratio(returns: pd.Series, risk_free: float = 0.0) -> float:
    excess = returns - risk_free / TRADING_DAYS
    downside = excess[excess < 0]
    dd_std = downside.std()
    if dd_std == 0 or np.isnan(dd_std):
        return 0.0
    return (excess.mean() / dd_std) * np.sqrt(TRADING_DAYS)


def max_drawdown(equity_curve: pd.Series) -> float:
    running_max = equity_curve.cummax()
    drawdown = (equity_curve - running_max) / running_max
    return drawdown.min()


def win_rate(returns: pd.Series) -> float:
    active = returns[returns != 0]
    if len(active) == 0:
        return 0.0
    return (active > 0).mean()


def calmar_ratio(equity_curve: pd.Series) -> float:
    mdd = max_drawdown(equity_curve)
    if mdd == 0:
        return 0.0
    return cagr(equity_curve) / abs(mdd)


def summarize(equity_curve: pd.Series, returns: pd.Series, trades: int) -> dict:
    return {
        "CAGR": float(round(cagr(equity_curve) * 100, 2)),
        "Sharpe": float(round(sharpe_ratio(returns), 2)),
        "Sortino": float(round(sortino_ratio(returns), 2)),
        "MaxDrawdown_%": float(round(max_drawdown(equity_curve) * 100, 2)),
        "Calmar": float(round(calmar_ratio(equity_curve), 2)),
        "WinRate_%": float(round(win_rate(returns) * 100, 2)),
        "Trades": int(trades),
        "FinalEquity": float(round(equity_curve.iloc[-1], 2)),
    }
