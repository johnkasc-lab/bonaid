"""
bonaid/dashboard/main.py
Local web dashboard - FastAPI backend serving JSON over the SAME Postgres
data every `bonaid` CLI command already reads/writes. No new source of
truth, no new database - this is purely a visual layer on top of what
already exists (positions, portfolio, P&L, decision history, macro regime).

Read-only by design: the dashboard never opens/closes positions itself -
that stays exclusively in `bonaid analyze` / `bonaid scan` / the scheduled
`bonaid check-positions` task, so there's exactly one place trading
decisions actually happen, and this just observes it.

Live-price-dependent views (drawdown) are cached briefly via Redis to
avoid re-fetching from yfinance on every page load/auto-refresh tick -
that would be slow and wasteful for a dashboard that refreshes every 30s.

Every DB/network-dependent endpoint is wrapped so a transient Postgres/
Redis/data-source hiccup returns a clean JSON error response instead of a
raw 500 - the dashboard's whole purpose is to show status even when
something's degraded, so it needs to itself be resilient to the things
it's reporting on.
"""
import functools
from datetime import datetime, timezone
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
import os

from bonaid.db import get_session
from bonaid.models import PaperPosition, AgentDecision
from bonaid.config import settings
from bonaid import cache

app = FastAPI(title="Bonaid Dashboard")

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def safe_endpoint(func):
    """Wraps a route so any unhandled exception (DB down, network error,
    etc.) becomes a clean JSON 503 with an 'error' field, instead of a raw
    500 or a crashed request. Applied to every data-fetching endpoint."""
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            return JSONResponse(status_code=503, content={"error": str(e)})
    return wrapper


@app.get("/")
def index():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


@app.get("/api/status")
@safe_endpoint
def api_status():
    checks = {}
    try:
        with get_session() as s:
            s.execute(__import__("sqlalchemy").text("SELECT 1"))
        checks["postgres"] = "ok"
    except Exception as e:
        checks["postgres"] = f"down: {e}"

    checks["redis"] = "ok" if cache.ping() else "down"
    return {"checks": checks, "timestamp": datetime.now(timezone.utc).isoformat()}


@app.get("/api/positions")
@safe_endpoint
def api_positions():
    with get_session() as s:
        rows = s.query(PaperPosition).filter(PaperPosition.status == "OPEN").order_by(PaperPosition.entry_date.desc()).all()
        return [
            {
                "ticker": r.ticker, "shares": r.shares, "entry_price": r.entry_price,
                "stop_loss": r.stop_loss, "take_profit": r.take_profit,
                "entry_confidence": r.entry_confidence,
                "entry_date": r.entry_date.isoformat() if r.entry_date else None,
            }
            for r in rows
        ]


@app.get("/api/portfolio")
@safe_endpoint
def api_portfolio():
    from bonaid.agents.portfolio_agent import get_portfolio_snapshot
    snap = get_portfolio_snapshot()
    return {
        "total_capital": snap.total_capital,
        "deployed_capital": snap.deployed_capital,
        "deployed_pct": snap.deployed_pct,
        "position_count": snap.position_count,
        "positions": [
            {"ticker": p.ticker, "shares": p.shares, "position_value": p.position_value,
             "pct_of_capital": p.pct_of_capital, "confidence": p.confidence}
            for p in snap.positions
        ],
        "warnings": snap.warnings,
    }


@app.get("/api/pnl")
@safe_endpoint
def api_pnl():
    from bonaid.agents.paper_trading import get_pnl_summary
    return get_pnl_summary()


@app.get("/api/drawdown")
@safe_endpoint
def api_drawdown():
    """Cached for 5 minutes (Redis) - this endpoint re-fetches live prices
    for every open position, which is slow and rate-limit-risky to do on
    every dashboard auto-refresh tick. `bonaid drawdown` (CLI) always
    fetches fresh; this cached version is specifically for the dashboard's
    frequent polling."""
    cached = cache.cache_get("dashboard:drawdown")
    if cached is not None:
        return {**cached, "cached": True}

    from bonaid.agents.paper_trading import evaluate_portfolio_drawdown
    from bonaid.analysis.data_fetcher import fetch_ohlcv

    with get_session() as s:
        open_positions = s.query(PaperPosition).filter(PaperPosition.status == "OPEN").all()
        positions_with_price = []
        for pos in open_positions:
            try:
                df = fetch_ohlcv(pos.ticker, years=1)
                current_price = round(float(df["Close"].iloc[-1]), 2)
                positions_with_price.append({
                    "ticker": pos.ticker, "shares": pos.shares,
                    "entry_price": pos.entry_price, "current_price": current_price,
                })
            except Exception:
                continue  # skip tickers that fail to fetch - don't block the whole dashboard

    result = evaluate_portfolio_drawdown(positions_with_price, settings.default_capital, settings.max_portfolio_drawdown_pct)
    cache.cache_set("dashboard:drawdown", result, ttl_seconds=300)
    return {**result, "cached": False}


@app.get("/api/macro")
@safe_endpoint
def api_macro():
    """Cached for 1 hour - FRED data doesn't change intra-day, no reason
    to hit the API on every dashboard refresh."""
    cached = cache.cache_get("dashboard:macro")
    if cached is not None:
        return {**cached, "cached": True}

    from bonaid.agents.macro_agent import get_macro_snapshot
    snapshot = get_macro_snapshot()
    result = {
        "regime": snapshot.regime,
        "fed_funds_rate": snapshot.fed_funds_rate,
        "fed_funds_rate_change_3m": snapshot.fed_funds_rate_change_3m,
        "cpi_yoy_pct": snapshot.cpi_yoy_pct,
        "unemployment_rate": snapshot.unemployment_rate,
        "treasury_10y": snapshot.treasury_10y,
        "reasons": snapshot.reasons,
    }
    cache.cache_set("dashboard:macro", result, ttl_seconds=3600)
    return {**result, "cached": False}


@app.get("/api/decisions")
@safe_endpoint
def api_decisions(limit: int = 20):
    with get_session() as s:
        rows = (
            s.query(AgentDecision)
            .order_by(AgentDecision.timestamp.desc())
            .limit(limit)
            .all()
        )
        return [
            {
                "ticker": r.ticker, "action": r.action, "confidence": r.confidence,
                "timestamp": r.timestamp.isoformat() if r.timestamp else None,
                "overridden": (r.supervisor_decision or {}).get("overridden", False),
            }
            for r in rows
        ]
