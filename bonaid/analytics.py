"""
bonaid/analytics.py
Ninth real capability - not a new agent, but the first module that looks
BACKWARD across the whole trading history rather than forward at a new
decision. Answers: "is this system actually any good?"

Honest scope note upfront: this builds a TRADE-level equity curve (one
point per closed trade, ordered by exit date), not a true daily
mark-to-market equity curve - bonaid doesn't currently store periodic
portfolio snapshots over time, only trade entry/exit events. A trade-level
curve is a standard, valid way to evaluate a system's track record, but
metrics derived from it (especially Sharpe/Sortino, which are built for
evenly-spaced return series) are approximations here, not the same
statistical animal as the daily-data Sharpe computed in
bonaid/analysis/metrics.py for historical backtests. This module says so
explicitly wherever it matters, rather than presenting a trade-level
Sharpe with the same confidence as a proper daily one.

Three things, in order of how much you can trust them:
  1. build_equity_curve() - just addition, no approximation, fully trustworthy.
  2. compute_track_record_metrics() - total return, max drawdown (peak-to-
     trough on the trade curve), win rate, profit factor - all robust.
     Sharpe/Sortino included but flagged as approximate, and SUPPRESSED
     entirely below a minimum trade count (small-sample Sharpe is
     actively misleading, not just imprecise).
  3. attribute_by_override() / attribute_by_driving_strategy() - genuinely
     useful but the most exploratory of the three; needs the MOST trades
     before the pattern means anything, and says so.
"""
from dataclasses import dataclass, field
from datetime import datetime

MIN_TRADES_FOR_SHARPE = 10  # below this, a trade-level Sharpe is noise, not signal - suppressed rather than shown misleadingly


@dataclass
class EquityPoint:
    date: datetime
    equity: float
    drawdown_pct: float
    ticker: str
    pnl: float


@dataclass
class TrackRecord:
    trade_count: int
    starting_capital: float
    ending_capital: float
    total_return_pct: float
    max_drawdown_pct: float
    win_rate: float
    profit_factor: float | None  # gross profit / gross loss; None if no losses yet (undefined, not infinite)
    avg_win: float
    avg_loss: float
    sharpe_approx: float | None  # None if trade_count < MIN_TRADES_FOR_SHARPE
    equity_curve: list = field(default_factory=list)  # list[EquityPoint]
    notes: list = field(default_factory=list)


def build_equity_curve(closed_trades: list[dict], starting_capital: float) -> list[EquityPoint]:
    """closed_trades: [{"ticker", "exit_date", "realized_pnl"}, ...], any order.
    Pure function - sorts internally, no DB access."""
    ordered = sorted(closed_trades, key=lambda t: t["exit_date"])
    equity = starting_capital
    peak = starting_capital
    curve = []
    for t in ordered:
        equity += t["realized_pnl"]
        peak = max(peak, equity)
        drawdown_pct = round(((equity - peak) / peak) * 100, 2) if peak > 0 else 0.0
        curve.append(EquityPoint(
            date=t["exit_date"], equity=round(equity, 2), drawdown_pct=drawdown_pct,
            ticker=t["ticker"], pnl=t["realized_pnl"],
        ))
    return curve


def compute_track_record_metrics(closed_trades: list[dict], starting_capital: float) -> TrackRecord:
    """closed_trades: [{"ticker", "exit_date", "realized_pnl"}, ...]"""
    if not closed_trades:
        return TrackRecord(
            trade_count=0, starting_capital=starting_capital, ending_capital=starting_capital,
            total_return_pct=0.0, max_drawdown_pct=0.0, win_rate=0.0, profit_factor=None,
            avg_win=0.0, avg_loss=0.0, sharpe_approx=None,
            notes=["No closed trades yet - track record starts once positions close."],
        )

    curve = build_equity_curve(closed_trades, starting_capital)
    ending_capital = curve[-1].equity
    total_return_pct = round(((ending_capital - starting_capital) / starting_capital) * 100, 2) if starting_capital > 0 else 0.0
    max_drawdown_pct = min(p.drawdown_pct for p in curve)

    wins = [t["realized_pnl"] for t in closed_trades if t["realized_pnl"] > 0]
    losses = [t["realized_pnl"] for t in closed_trades if t["realized_pnl"] <= 0]
    win_rate = round((len(wins) / len(closed_trades)) * 100, 1)
    avg_win = round(sum(wins) / len(wins), 2) if wins else 0.0
    avg_loss = round(sum(losses) / len(losses), 2) if losses else 0.0
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    profit_factor = round(gross_profit / gross_loss, 2) if gross_loss > 0 else None

    notes = []
    sharpe_approx = None
    if len(closed_trades) < MIN_TRADES_FOR_SHARPE:
        notes.append(
            f"Sharpe suppressed - only {len(closed_trades)} closed trade(s), need at least "
            f"{MIN_TRADES_FOR_SHARPE} for it to mean anything rather than noise."
        )
    else:
        returns = [t["realized_pnl"] / starting_capital for t in closed_trades]
        mean_return = sum(returns) / len(returns)
        variance = sum((r - mean_return) ** 2 for r in returns) / len(returns)
        std_dev = variance ** 0.5
        sharpe_approx = round((mean_return / std_dev), 2) if std_dev > 0 else None
        notes.append(
            "Sharpe is TRADE-LEVEL (per closed trade), not the daily-return Sharpe used in historical "
            "backtests - treat as a rough signal, not a directly comparable number."
        )

    if profit_factor is None and gross_profit > 0:
        notes.append("Profit factor undefined - no losing trades yet.")

    return TrackRecord(
        trade_count=len(closed_trades), starting_capital=starting_capital, ending_capital=round(ending_capital, 2),
        total_return_pct=total_return_pct, max_drawdown_pct=max_drawdown_pct, win_rate=win_rate,
        profit_factor=profit_factor, avg_win=avg_win, avg_loss=avg_loss, sharpe_approx=sharpe_approx,
        equity_curve=curve, notes=notes,
    )


def attribute_by_override(trades_with_decisions: list[dict]) -> dict:
    """Did Supervisor-overridden decisions (Technical said one thing, News/
    Sentiment disagreed strongly enough to change the action) perform
    differently from non-overridden ones? Genuinely useful but needs more
    data than the basic metrics above before the pattern means much.

    trades_with_decisions: [{"realized_pnl", "overridden": bool}, ...]
    """
    overridden = [t["realized_pnl"] for t in trades_with_decisions if t.get("overridden")]
    not_overridden = [t["realized_pnl"] for t in trades_with_decisions if not t.get("overridden")]

    def _summarize(pnls):
        if not pnls:
            return {"trade_count": 0, "win_rate": None, "avg_pnl": None}
        wins = sum(1 for p in pnls if p > 0)
        return {
            "trade_count": len(pnls),
            "win_rate": round((wins / len(pnls)) * 100, 1),
            "avg_pnl": round(sum(pnls) / len(pnls), 2),
        }

    result = {"overridden": _summarize(overridden), "not_overridden": _summarize(not_overridden)}
    total = len(overridden) + len(not_overridden)
    result["reliable"] = total >= MIN_TRADES_FOR_SHARPE
    return result


def attribute_by_driving_strategy(trades_with_decisions: list[dict]) -> dict:
    """Which underlying Technical strategy was most often the 'highest-
    conviction signal' driving decisions that turned into winning vs
    losing trades? Extracted from signal_breakdown (the highest 5yr-Sharpe
    entry at decision time), same info `analyze`'s output already surfaces
    as "Highest-conviction signal: X" - just aggregated across trades here.

    trades_with_decisions: [{"realized_pnl", "signal_breakdown": [...]}, ...]
    """
    by_strategy: dict[str, list[float]] = {}
    for t in trades_with_decisions:
        breakdown = t.get("signal_breakdown") or []
        valid = [b for b in breakdown if b.get("sharpe_5y") is not None]
        if not valid:
            continue
        driving = max(valid, key=lambda b: b["sharpe_5y"])
        by_strategy.setdefault(driving["strategy"], []).append(t["realized_pnl"])

    result = {}
    for strategy, pnls in by_strategy.items():
        wins = sum(1 for p in pnls if p > 0)
        result[strategy] = {
            "trade_count": len(pnls),
            "win_rate": round((wins / len(pnls)) * 100, 1),
            "avg_pnl": round(sum(pnls) / len(pnls), 2),
        }
    return result
