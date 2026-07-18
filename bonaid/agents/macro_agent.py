"""
bonaid/agents/macro_agent.py
Eighth real agent, and the first one whose signal isn't ticker-specific -
macro conditions apply to every position at once, not one at a time.

Source: FRED (Federal Reserve Economic Data) - genuinely free, a one-time
no-cost API key signup, no meaningful rate limits at this scale.

Four indicators, each with a well-understood, textbook relationship to
equity conditions:
  - Fed Funds Rate (FEDFUNDS)     - the base cost of money
  - CPI, year-over-year (CPIAUCSL) - inflation
  - Unemployment Rate (UNRATE)     - labor market slack
  - 10-Year Treasury Yield (DGS10) - long-term rate expectations

Regime classification: simple, legible rules (not a black-box score) that
bucket current conditions into "Tightening" / "Easing" / "Neutral" - same
philosophy as Supervisor's reconciliation logic: a human should be able to
read the rule and understand exactly why a given regime was assigned.

INFORMATIONAL ONLY today, matching the precedent set with News/Sentiment -
Supervisor doesn't factor this into BUY/SELL decisions yet. Macro
conditions apply market-wide, not per-ticker, so wiring it into
Supervisor's per-ticker reconciliation logic needs its own deliberate
design pass, not a default bolt-on.
"""
from dataclasses import dataclass, field
import requests

from bonaid.config import settings

FRED_URL = "https://api.stlouisfed.org/fred/series/observations"

SERIES = {
    "fed_funds_rate": "FEDFUNDS",
    "cpi": "CPIAUCSL",
    "unemployment_rate": "UNRATE",
    "treasury_10y": "DGS10",
}


@dataclass
class MacroSnapshot:
    regime: str                    # "Tightening" | "Easing" | "Neutral" | "No Data"
    fed_funds_rate: float | None = None
    fed_funds_rate_change_3m: float | None = None
    cpi_yoy_pct: float | None = None
    unemployment_rate: float | None = None
    treasury_10y: float | None = None
    reasons: list = field(default_factory=list)


def _fetch_series(series_id: str, limit: int = 15, timeout: int = 10) -> list[dict]:
    """Returns a list of {date, value} dicts, most recent last. Returns an
    empty list (not an exception) on any failure or missing API key, so
    this is always safe to call unconditionally."""
    if not settings.fred_api_key:
        return []

    try:
        resp = requests.get(
            FRED_URL,
            params={
                "series_id": series_id,
                "api_key": settings.fred_api_key,
                "file_type": "json",
                "sort_order": "desc",
                "limit": limit,
            },
            timeout=timeout,
        )
        if resp.status_code != 200:
            print(f"[macro_agent] FRED fetch for '{series_id}' returned HTTP {resp.status_code}: {resp.text[:200]!r}")
            return []
        data = resp.json()
        observations = [
            {"date": o["date"], "value": float(o["value"])}
            for o in data.get("observations", [])
            if o.get("value") not in (".", None)  # FRED uses "." for missing data points
        ]
        return list(reversed(observations))  # oldest-first, easier to reason about trend
    except Exception as e:
        print(f"[macro_agent] FRED fetch for '{series_id}' raised {type(e).__name__}: {e}")
        return []


def _classify_regime(fed_funds_change_3m: float | None, cpi_yoy: float | None) -> tuple[str, list[str]]:
    """Simple, legible rules - not a black-box score. A human should be
    able to read this and know exactly why a regime was assigned."""
    if fed_funds_change_3m is None:
        return "No Data", ["Insufficient FRED data to classify current regime."]

    reasons = []
    if fed_funds_change_3m > 0.1:
        regime = "Tightening"
        reasons.append(f"Fed Funds Rate has risen {fed_funds_change_3m:+.2f} points over the last ~3 months.")
    elif fed_funds_change_3m < -0.1:
        regime = "Easing"
        reasons.append(f"Fed Funds Rate has fallen {fed_funds_change_3m:+.2f} points over the last ~3 months.")
    else:
        regime = "Neutral"
        reasons.append(f"Fed Funds Rate has been roughly flat ({fed_funds_change_3m:+.2f} points) over the last ~3 months.")

    if cpi_yoy is not None:
        if cpi_yoy > 3.5:
            reasons.append(f"Inflation (CPI, YoY) is elevated at {cpi_yoy:.1f}%, above the Fed's ~2% target.")
        elif cpi_yoy < 1.5:
            reasons.append(f"Inflation (CPI, YoY) is low at {cpi_yoy:.1f}%.")
        else:
            reasons.append(f"Inflation (CPI, YoY) is near-target at {cpi_yoy:.1f}%.")

    return regime, reasons


def get_macro_snapshot() -> MacroSnapshot:
    """Fetches all 4 series and classifies the current regime. Not
    ticker-specific - one snapshot describes market-wide conditions."""
    fed_funds = _fetch_series(SERIES["fed_funds_rate"])
    cpi = _fetch_series(SERIES["cpi"], limit=15)
    unemployment = _fetch_series(SERIES["unemployment_rate"])
    treasury_10y = _fetch_series(SERIES["treasury_10y"])

    if not fed_funds:
        return MacroSnapshot(regime="No Data", reasons=["FRED not configured or unreachable - set FRED_API_KEY in .env."])

    current_fed_funds = fed_funds[-1]["value"]
    fed_funds_3m_ago = fed_funds[-4]["value"] if len(fed_funds) >= 4 else fed_funds[0]["value"]
    fed_funds_change_3m = round(current_fed_funds - fed_funds_3m_ago, 2)

    cpi_yoy = None
    if len(cpi) >= 13:  # need ~12 months back for a YoY comparison
        cpi_yoy = round(((cpi[-1]["value"] / cpi[-13]["value"]) - 1) * 100, 2)

    current_unemployment = unemployment[-1]["value"] if unemployment else None
    current_10y = treasury_10y[-1]["value"] if treasury_10y else None

    regime, reasons = _classify_regime(fed_funds_change_3m, cpi_yoy)
    if current_unemployment is not None:
        reasons.append(f"Unemployment rate: {current_unemployment}%.")
    if current_10y is not None:
        reasons.append(f"10-Year Treasury yield: {current_10y}%.")

    return MacroSnapshot(
        regime=regime,
        fed_funds_rate=current_fed_funds,
        fed_funds_rate_change_3m=fed_funds_change_3m,
        cpi_yoy_pct=cpi_yoy,
        unemployment_rate=current_unemployment,
        treasury_10y=current_10y,
        reasons=reasons,
    )
