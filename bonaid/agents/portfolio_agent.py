"""
bonaid/agents/portfolio_agent.py
Sixth real agent, and the first one that looks ACROSS decisions rather than
analyzing one ticker in isolation.

Honest scope note: there's no paper trading or broker fill simulation yet
(that's the next roadmap item), so there's no real "open position" state to
track. What this agent does instead: treats the MOST RECENT logged decision
per ticker as the implied current stance, and - for any ticker where that
latest decision was a sized BUY - treats it as an implied open position.
This is genuinely useful today (aggregate exposure, concentration
warnings) without pretending infrastructure exists that doesn't yet. Once
Paper Trading exists, this agent should be pointed at real fill/position
records instead of inferring from the decision log.
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class PortfolioPosition:
    ticker: str
    shares: int
    position_value: float
    pct_of_capital: float
    confidence: float
    as_of: datetime


@dataclass
class PortfolioSnapshot:
    total_capital: float
    deployed_capital: float
    deployed_pct: float
    position_count: int
    positions: list = field(default_factory=list)   # list[PortfolioPosition]
    warnings: list = field(default_factory=list)


def _dedupe_latest_per_ticker(decisions: list[dict]) -> list[dict]:
    """Keeps only the most recent decision per ticker - the decision log
    accumulates one row per `bonaid analyze` call, so the same ticker
    analyzed twice should only count once, using its latest stance."""
    latest_by_ticker = {}
    for d in sorted(decisions, key=lambda x: x["timestamp"], reverse=True):
        if d["ticker"] not in latest_by_ticker:
            latest_by_ticker[d["ticker"]] = d
    return list(latest_by_ticker.values())


def build_snapshot_from_decisions(
    decisions: list[dict],
    capital: float,
    max_total_exposure_pct: float = 50.0,
) -> PortfolioSnapshot:
    """LEGACY - inferred exposure from the decision log, used before Paper
    Trading existed and there was no real position state to read. Kept
    (and still tested) for backward compatibility, but
    build_snapshot_from_positions() below is what get_portfolio_snapshot()
    actually uses now that real position records exist."""
    latest = _dedupe_latest_per_ticker(decisions)

    positions = []
    for d in latest:
        risk = d.get("risk_assessment") or {}
        if d["action"] == "BUY" and risk.get("tradeable"):
            positions.append(PortfolioPosition(
                ticker=d["ticker"],
                shares=risk["position_shares"],
                position_value=risk["position_value"],
                pct_of_capital=risk["position_pct_of_capital"],
                confidence=d["confidence"],
                as_of=d["timestamp"],
            ))

    deployed_capital = round(sum(p.position_value for p in positions), 2)
    deployed_pct = round((deployed_capital / capital) * 100, 2) if capital > 0 else 0.0

    warnings = []
    if deployed_pct > max_total_exposure_pct:
        warnings.append(
            f"Total implied exposure ({deployed_pct}%) exceeds the {max_total_exposure_pct}% "
            f"total-exposure guideline, even though each individual position respects its own cap. "
            f"Concentration risk across positions, not just within one."
        )
    if len(positions) == 0:
        warnings.append("No open positions implied by decision history - nothing currently sized as BUY.")

    # Simple duplicate-sector-style heuristic without needing real sector
    # data yet: flag if the SAME ticker root shows up (e.g. multiple share
    # classes) - genuinely useful cheap check, not a substitute for real
    # correlation analysis which needs price data across positions.
    tickers_seen = [p.ticker.split(".")[0] for p in positions]
    if len(tickers_seen) != len(set(tickers_seen)):
        warnings.append("Multiple positions appear to reference the same underlying company (different share classes/exchanges).")

    return PortfolioSnapshot(
        total_capital=capital,
        deployed_capital=deployed_capital,
        deployed_pct=deployed_pct,
        position_count=len(positions),
        positions=sorted(positions, key=lambda p: p.position_value, reverse=True),
        warnings=warnings,
    )


def get_portfolio_snapshot(capital: float | None = None) -> PortfolioSnapshot:
    """DB-backed entrypoint - reads REAL open PaperPosition records (not
    inferred from the decision log - that was the pre-Paper-Trading
    approach, see build_snapshot_from_decisions above for the legacy
    version still kept for tests/reference)."""
    from bonaid.db import get_session
    from bonaid.models import PaperPosition
    from bonaid.config import settings

    capital = capital if capital is not None else settings.default_capital

    with get_session() as session:
        rows = session.query(PaperPosition).filter(PaperPosition.status == "OPEN").all()
        positions_data = [
            {"ticker": r.ticker, "shares": r.shares, "entry_price": r.entry_price, "entry_confidence": r.entry_confidence}
            for r in rows
        ]

    return build_snapshot_from_positions(positions_data, capital, settings.max_total_exposure_pct, settings.max_sector_exposure_pct)


def build_snapshot_from_positions(
    positions_data: list[dict],
    capital: float,
    max_total_exposure_pct: float = 50.0,
    max_sector_exposure_pct: float = 25.0,
) -> PortfolioSnapshot:
    """Pure function - takes real open-position dicts (ticker, shares,
    entry_price), no DB access. This is what get_portfolio_snapshot() uses
    now that Paper Trading provides real position records."""
    from bonaid.universe import sector_of

    positions = []
    for p in positions_data:
        value = round(p["shares"] * p["entry_price"], 2)
        pct = round((value / capital) * 100, 2) if capital > 0 else 0.0
        positions.append(PortfolioPosition(
            ticker=p["ticker"], shares=p["shares"], position_value=value,
            pct_of_capital=pct, confidence=p.get("entry_confidence") or 0.0, as_of=datetime.now(timezone.utc),
        ))

    deployed_capital = round(sum(p.position_value for p in positions), 2)
    deployed_pct = round((deployed_capital / capital) * 100, 2) if capital > 0 else 0.0

    warnings = []
    if deployed_pct > max_total_exposure_pct:
        warnings.append(
            f"Total exposure ({deployed_pct}%) exceeds the {max_total_exposure_pct}% "
            f"total-exposure guideline, even though each individual position respects its own cap."
        )
    if len(positions) == 0:
        warnings.append("No open positions.")

    tickers_seen = [p.ticker.split(".")[0] for p in positions]
    if len(tickers_seen) != len(set(tickers_seen)):
        warnings.append("Multiple positions appear to reference the same underlying company (different share classes/exchanges).")

    # Sector concentration - N different tickers can still be one correlated
    # bet if they're all the same sector (e.g. JPM+BAC+GS all moving on the
    # same financials-sector catalyst). Individual position caps don't catch
    # this; this check specifically looks across positions, not within one.
    sector_totals: dict[str, float] = {}
    for p in positions:
        sector = sector_of(p.ticker)
        sector_totals[sector] = sector_totals.get(sector, 0.0) + p.position_value
    for sector, total in sector_totals.items():
        sector_pct = round((total / capital) * 100, 2) if capital > 0 else 0.0
        if sector_pct > max_sector_exposure_pct and sector != "Unknown":
            warnings.append(
                f"Sector concentration: {sector} positions total {sector_pct}% of capital, "
                f"exceeding the {max_sector_exposure_pct}% single-sector guideline - "
                f"multiple tickers, but a correlated bet."
            )

    return PortfolioSnapshot(
        total_capital=capital,
        deployed_capital=deployed_capital,
        deployed_pct=deployed_pct,
        position_count=len(positions),
        positions=sorted(positions, key=lambda p: p.position_value, reverse=True),
        warnings=warnings,
    )
