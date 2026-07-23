"""
bonaid/diagnostics.py
"Understand and summarize what went wrong" - honestly scoped. This module
CLASSIFIES and EXPLAINS failures (SSL/TLS blips, rate limits, unsupported
symbols, etc.) and suggests what to do about them. It does NOT
autonomously rewrite code - a trading system silently modifying its own
logic with no human review is a real safety problem, not a convenience.
Every fix this conversation has made has gone through the same reviewed
loop (diagnose -> propose -> test -> you approve -> deploy); this module
is the "diagnose" step made systematic and queryable, not a bypass of the
rest of that loop.

Classification is simple substring matching, not ML - deliberately, so a
human can read CATEGORY_RULES below and know exactly why something was
classified the way it was. Same "legible over black box" philosophy as
Supervisor/Macro/the ML model's plain logistic regression.
"""
from collections import defaultdict
from datetime import datetime, timedelta

# Ordered - first matching rule wins. Each entry: (category, [substrings to match, case-insensitive])
CATEGORY_RULES = [
    ("SSL/TLS transient", ["ssl", "tls", "wrong_version_number", "protocol_version", "decode_error"]),
    ("Blocked / rate-limited (403/401)", ["403", "401", "forbidden", "unauthorized"]),
    ("Symbol not supported (404)", ["404", "symbol not found", "no data returned"]),
    ("Timeout", ["timeout", "timed out"]),
    ("Not configured", ["not configured", "no api key", "credentials"]),
]

REMEDIATIONS = {
    "SSL/TLS transient": (
        "Known intermittent issue affecting HTTPS calls from inside Docker/WSL2 to some hosts "
        "(yfinance, StockTwits) - usually a one-off, the next call typically succeeds. If it happens "
        "on the large majority of calls rather than occasionally, it may be a WSL2 network MTU issue - "
        "worth a `wsl --shutdown` and Docker Desktop restart."
    ),
    "Blocked / rate-limited (403/401)": (
        "The source is rejecting the request outright, not just being slow. For Reddit specifically: "
        "check the linked account's email is verified and updated API terms are accepted at "
        "reddit.com/prefs/apps. For other sources, check API keys/credentials in .env are current."
    ),
    "Symbol not supported (404)": (
        "Expected, not a bug - the data source doesn't recognize this ticker format (e.g. crypto "
        "'BTC-USD' or forex 'EURUSD=X' aren't valid StockTwits symbols). The system already degrades "
        "gracefully here (falls back or shows 'No Data') - no action needed."
    ),
    "Timeout": (
        "The request took too long and was abandoned. Usually transient network slowness. If "
        "persistent for one specific source, that source may be having an outage."
    ),
    "Not configured": (
        "A credential/API key is missing from .env for this feature (Reddit, FRED, alerts, etc). "
        "Not an error in the running system - just an optional feature that hasn't been set up yet."
    ),
}

UNCATEGORIZED_REMEDIATION = "Uncategorized - doesn't match a known pattern. Worth reading the full message and, if it recurs, sharing it for a proper fix."


def classify_error(message: str) -> str:
    """Pure function - simple substring matching against CATEGORY_RULES.
    Returns 'Uncategorized' if nothing matches."""
    lowered = message.lower()
    for category, substrings in CATEGORY_RULES:
        if any(s in lowered for s in substrings):
            return category
    return "Uncategorized"


def log_error(component: str, message: str, ticker: str | None = None):
    """Best-effort DB write - if this itself fails (e.g. DB down), it
    swallows the exception rather than raising, since logging a failure
    must never itself crash the agent that's already failing at something
    else. Also still prints, preserving the existing visible-in-terminal
    behavior everywhere this is called from."""
    print(f"[{component}] {message}")
    try:
        from bonaid.db import get_session
        from bonaid.models import ErrorLog
        with get_session() as s:
            s.add(ErrorLog(component=component, ticker=ticker, message=message))
    except Exception:
        pass  # logging the error must never itself be the thing that crashes


def summarize_errors(entries: list, since_hours: int = 24) -> dict:
    """Pure function - entries: [{"timestamp", "component", "ticker",
    "message"}, ...]. Filters to the last `since_hours`, classifies each,
    and aggregates counts + a couple of example messages per category."""
    cutoff = datetime.utcnow() - timedelta(hours=since_hours)
    recent = [e for e in entries if e["timestamp"] >= cutoff]

    by_category = defaultdict(lambda: {"count": 0, "components": set(), "examples": []})
    for e in recent:
        category = classify_error(e["message"])
        bucket = by_category[category]
        bucket["count"] += 1
        bucket["components"].add(e["component"])
        if len(bucket["examples"]) < 3:
            bucket["examples"].append(e["message"][:200])

    result = {
        "total_errors": len(recent),
        "since_hours": since_hours,
        "categories": {},
    }
    for category, data in sorted(by_category.items(), key=lambda kv: kv[1]["count"], reverse=True):
        result["categories"][category] = {
            "count": data["count"],
            "components": sorted(data["components"]),
            "examples": data["examples"],
            "remediation": REMEDIATIONS.get(category, UNCATEGORIZED_REMEDIATION),
        }
    return result


def get_recent_errors_from_db(since_hours: int = 24) -> dict:
    """DB-backed entrypoint - thin wrapper around summarize_errors()."""
    from bonaid.db import get_session
    from bonaid.models import ErrorLog

    with get_session() as s:
        rows = s.query(ErrorLog).all()
        entries = [
            {"timestamp": r.timestamp, "component": r.component, "ticker": r.ticker, "message": r.message}
            for r in rows
        ]
    return summarize_errors(entries, since_hours=since_hours)
