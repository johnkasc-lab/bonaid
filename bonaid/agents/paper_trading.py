"""
bonaid/agents/paper_trading.py
Seventh real agent. Simulates order execution and tracks real (not
inferred) open positions with actual stop-loss/take-profit monitoring.

Two pure functions do the actual decision logic (unit-testable without a
DB or live prices):
  - should_close_position(): given a current price and a position's
    stop/take-profit levels, decides whether to close and why
  - compute_pnl(): simple realized P&L math

Everything else is DB/IO plumbing around those two functions - open a
position, check all open positions against live prices, close positions
that hit their exit levels.
"""
from dataclasses import dataclass
from datetime import datetime


@dataclass
class CloseCheck:
    should_close: bool
    reason: str | None  # "stop_loss" | "take_profit" | None


def should_close_position(current_price: float, stop_loss: float, take_profit: float) -> CloseCheck:
    """Long-only (matches the rest of the system - Risk Agent only sizes
    long entries). Stop-loss checked before take-profit: if a single price
    move somehow spans both levels in one check (e.g. an overnight gap),
    treat it as the stop being hit - conservative assumption, protecting
    capital takes priority over capturing the extra gain."""
    if current_price <= stop_loss:
        return CloseCheck(should_close=True, reason="stop_loss")
    if current_price >= take_profit:
        return CloseCheck(should_close=True, reason="take_profit")
    return CloseCheck(should_close=False, reason=None)


def compute_pnl(entry_price: float, exit_price: float, shares: int) -> float:
    return round((exit_price - entry_price) * shares, 2)


def open_position(ticker: str, shares: int, entry_price: float, stop_loss: float, take_profit: float, entry_confidence: float | None = None):
    """Opens a new paper position, UNLESS:
      1. One is already open for this ticker (prevents silently doubling
         up exposure on repeated BUY signals across multiple calls), OR
      2. Opening it would push TOTAL portfolio exposure past
         settings.max_total_exposure_pct.

    That second check is the important one - Risk Agent caps each
    INDIVIDUAL position at max_position_pct (default 10%), but nothing
    previously stopped the AGGREGATE from blowing past the total-exposure
    guideline when many tickers fire BUY in the same session (e.g. a
    `bonaid scan` across dozens of tickers in market-wide bullish
    conditions). This is a hard gate here in open_position() itself - not
    just a warning shown later by `bonaid portfolio` - specifically so it
    can't be bypassed by any caller (analyze, scan, or future automation).
    Returns (position_or_none, message)."""
    from bonaid.db import get_session
    from bonaid.models import PaperPosition
    from bonaid.config import settings

    position_value = round(shares * entry_price, 2)
    capital = settings.default_capital

    with get_session() as session:
        existing = (
            session.query(PaperPosition)
            .filter(PaperPosition.ticker == ticker, PaperPosition.status == "OPEN")
            .first()
        )
        if existing:
            return None, f"Position already open for {ticker} ({existing.shares} shares @ ${existing.entry_price}) - not opening a duplicate."

        open_positions = session.query(PaperPosition).filter(PaperPosition.status == "OPEN").all()
        currently_deployed = sum(p.shares * p.entry_price for p in open_positions)
        projected_deployed = currently_deployed + position_value
        projected_pct = round((projected_deployed / capital) * 100, 2) if capital > 0 else 0.0

        if projected_pct > settings.max_total_exposure_pct:
            current_pct = round((currently_deployed / capital) * 100, 2) if capital > 0 else 0.0
            from bonaid.notifier import notify_exposure_refused
            notify_exposure_refused(ticker, projected_pct, settings.max_total_exposure_pct)
            return None, (
                f"REFUSED to open {ticker}: would bring total exposure to {projected_pct}%, exceeding the "
                f"{settings.max_total_exposure_pct}% guideline (currently {current_pct}% deployed across "
                f"{len(open_positions)} position(s)). Close existing positions, or raise "
                f"MAX_TOTAL_EXPOSURE_PCT in .env if this is intentional."
            )

        position = PaperPosition(
            ticker=ticker,
            shares=shares,
            entry_price=entry_price,
            entry_confidence=entry_confidence,
            stop_loss=stop_loss,
            take_profit=take_profit,
            status="OPEN",
        )
        session.add(position)
        session.flush()
        pid = position.id
        from bonaid.notifier import notify_position_opened
        notify_position_opened(ticker, shares, entry_price, stop_loss, take_profit, entry_confidence or 0.0)
        return pid, f"Opened paper position: {shares} shares of {ticker} @ ${entry_price} (stop ${stop_loss}, target ${take_profit})."


def evaluate_portfolio_drawdown(open_positions: list[dict], capital: float, max_drawdown_pct: float) -> dict:
    """Pure function - given open positions with their current prices,
    computes TOTAL unrealized P&L across all of them and checks it against
    the portfolio-level drawdown guideline. This is what individual
    stop-losses on each position DON'T catch: every position can be sitting
    just above its own stop, and the portfolio can still be down badly in
    aggregate if the market broadly moves against you at once.

    open_positions: [{"ticker", "shares", "entry_price", "current_price"}, ...]
    """
    total_unrealized_pnl = sum(
        (p["current_price"] - p["entry_price"]) * p["shares"] for p in open_positions
    )
    drawdown_pct = round((total_unrealized_pnl / capital) * 100, 2) if capital > 0 else 0.0
    breached = drawdown_pct <= -abs(max_drawdown_pct)
    return {
        "total_unrealized_pnl": round(total_unrealized_pnl, 2),
        "drawdown_pct": drawdown_pct,
        "breached": breached,
        "position_count": len(open_positions),
    }


def check_all_positions(use_synthetic: bool = False) -> list[dict]:
    """Checks every OPEN position against its latest live price, closing
    any that hit stop-loss or take-profit. THEN checks the portfolio-level
    drawdown across whatever remains open (see evaluate_portfolio_drawdown)
    - if breached, sends an alert, and additionally auto-closes every
    remaining open position if settings.auto_close_on_drawdown is True (a
    real kill switch, off by default - see config.py). Returns a list of
    what happened - empty list if nothing changed. Safe to run on a
    schedule independent of any specific `analyze` call."""
    from bonaid.db import get_session
    from bonaid.models import PaperPosition
    from bonaid.config import settings

    if use_synthetic:
        from bonaid.analysis.synthetic_data import generate_universe
    else:
        from bonaid.analysis.data_fetcher import fetch_ohlcv

    events = []
    still_open_with_price = []  # feeds the portfolio-level drawdown check below

    with get_session() as session:
        open_positions = session.query(PaperPosition).filter(PaperPosition.status == "OPEN").all()
        for pos in open_positions:
            try:
                if use_synthetic:
                    df = generate_universe([pos.ticker], years=1)[pos.ticker]
                else:
                    df = fetch_ohlcv(pos.ticker, years=1)
                current_price = round(float(df["Close"].iloc[-1]), 2)
            except Exception as e:
                events.append({"ticker": pos.ticker, "event": "price_fetch_failed", "detail": str(e)})
                continue

            check = should_close_position(current_price, pos.stop_loss, pos.take_profit)
            if check.should_close:
                pnl = compute_pnl(pos.entry_price, current_price, pos.shares)
                pos.status = "CLOSED"
                pos.exit_price = current_price
                pos.exit_date = datetime.utcnow()
                pos.exit_reason = check.reason
                pos.realized_pnl = pnl
                from bonaid.notifier import notify_position_closed
                notify_position_closed(pos.ticker, pos.shares, current_price, check.reason, pnl)
                events.append({
                    "ticker": pos.ticker, "event": "closed", "reason": check.reason,
                    "exit_price": current_price, "pnl": pnl, "shares": pos.shares,
                })
            else:
                still_open_with_price.append({
                    "ticker": pos.ticker, "shares": pos.shares,
                    "entry_price": pos.entry_price, "current_price": current_price,
                })
                events.append({
                    "ticker": pos.ticker, "event": "held", "current_price": current_price,
                    "stop_loss": pos.stop_loss, "take_profit": pos.take_profit,
                })

        # Portfolio-level drawdown check, across whatever's still open after
        # the individual stop/take-profit pass above.
        if still_open_with_price:
            drawdown = evaluate_portfolio_drawdown(still_open_with_price, settings.default_capital, settings.max_portfolio_drawdown_pct)
            if drawdown["breached"]:
                from bonaid.notifier import notify_portfolio_drawdown
                notify_portfolio_drawdown(drawdown["drawdown_pct"], drawdown["total_unrealized_pnl"], settings.auto_close_on_drawdown)
                events.append({"event": "portfolio_drawdown_breached", **drawdown})

                if settings.auto_close_on_drawdown:
                    for p in still_open_with_price:
                        pos = session.query(PaperPosition).filter(
                            PaperPosition.ticker == p["ticker"], PaperPosition.status == "OPEN"
                        ).first()
                        if not pos:
                            continue
                        pnl = compute_pnl(pos.entry_price, p["current_price"], pos.shares)
                        pos.status = "CLOSED"
                        pos.exit_price = p["current_price"]
                        pos.exit_date = datetime.utcnow()
                        pos.exit_reason = "portfolio_drawdown_kill_switch"
                        pos.realized_pnl = pnl
                        from bonaid.notifier import notify_position_closed
                        notify_position_closed(pos.ticker, pos.shares, p["current_price"], "portfolio_drawdown_kill_switch", pnl)
                        events.append({
                            "ticker": pos.ticker, "event": "closed", "reason": "portfolio_drawdown_kill_switch",
                            "exit_price": p["current_price"], "pnl": pnl, "shares": pos.shares,
                        })
    return events


def close_position_manually(ticker: str, exit_price: float) -> str:
    """Manual override to close a position at a given price, regardless of
    whether stop/take-profit has actually been hit - e.g. the user decides
    to exit early for a reason the system doesn't model."""
    from bonaid.db import get_session
    from bonaid.models import PaperPosition

    with get_session() as session:
        pos = (
            session.query(PaperPosition)
            .filter(PaperPosition.ticker == ticker, PaperPosition.status == "OPEN")
            .first()
        )
        if not pos:
            return f"No open position found for {ticker}."

        pnl = compute_pnl(pos.entry_price, exit_price, pos.shares)
        pos.status = "CLOSED"
        pos.exit_price = exit_price
        pos.exit_date = datetime.utcnow()
        pos.exit_reason = "manual"
        pos.realized_pnl = pnl
        from bonaid.notifier import notify_position_closed
        notify_position_closed(ticker, pos.shares, exit_price, "manual", pnl)
        return f"Closed {ticker}: {pos.shares} shares @ ${exit_price}, realized P&L ${pnl:,.2f}."


def get_pnl_summary() -> dict:
    """Aggregate stats across all CLOSED positions."""
    from bonaid.db import get_session
    from bonaid.models import PaperPosition

    with get_session() as session:
        closed = session.query(PaperPosition).filter(PaperPosition.status == "CLOSED").all()

    if not closed:
        return {"trade_count": 0, "total_pnl": 0.0, "win_rate": 0.0, "wins": 0, "losses": 0}

    total_pnl = round(sum(p.realized_pnl for p in closed), 2)
    wins = sum(1 for p in closed if p.realized_pnl > 0)
    losses = sum(1 for p in closed if p.realized_pnl <= 0)
    win_rate = round((wins / len(closed)) * 100, 1) if closed else 0.0

    return {
        "trade_count": len(closed),
        "total_pnl": total_pnl,
        "win_rate": win_rate,
        "wins": wins,
        "losses": losses,
    }
