"""
tests/test_diagnostics.py
Tests bonaid/diagnostics.py's classification and summarization logic
against the actual real error message patterns seen during live testing
this session (StockTwits SSL errors, Reddit 401s, 404s for crypto/forex
symbols). No DB needed - log_error's DB write is tested for graceful
failure separately.
"""
from datetime import datetime, timedelta
from bonaid.diagnostics import classify_error, summarize_errors, log_error


def test_classify_ssl_tls_errors():
    assert classify_error("SSLError: WRONG_VERSION_NUMBER") == "SSL/TLS transient"
    assert classify_error("TLS connect error: protocol version") == "SSL/TLS transient"


def test_classify_rate_limited_errors():
    assert classify_error("HTTP 401 - Unauthorized") == "Blocked / rate-limited (403/401)"
    assert classify_error("returned HTTP 403 (not 200)") == "Blocked / rate-limited (403/401)"


def test_classify_symbol_not_found():
    assert classify_error("returned HTTP 404: Symbol not found") == "Symbol not supported (404)"


def test_classify_not_configured():
    assert classify_error("Reddit not configured - set REDDIT_CLIENT_ID") == "Not configured"


def test_classify_uncategorized_for_unknown_pattern():
    assert classify_error("Something totally unexpected and new") == "Uncategorized"


def test_classification_order_ssl_wins_over_generic_text():
    # A message could plausibly contain multiple substrings - first rule
    # in CATEGORY_RULES should win, deterministically.
    msg = "SSLError somehow also mentions 404 in passing"
    assert classify_error(msg) == "SSL/TLS transient"


def test_summarize_errors_filters_by_time_window():
    now = datetime.utcnow()
    entries = [
        {"timestamp": now - timedelta(minutes=5), "component": "sentiment_agent", "ticker": "AAPL", "message": "HTTP 401"},
        {"timestamp": now - timedelta(hours=30), "component": "sentiment_agent", "ticker": "MSFT", "message": "HTTP 401"},
    ]
    result = summarize_errors(entries, since_hours=24)
    assert result["total_errors"] == 1


def test_summarize_errors_aggregates_by_category():
    now = datetime.utcnow()
    entries = [
        {"timestamp": now, "component": "sentiment_agent", "ticker": "A", "message": "SSLError"},
        {"timestamp": now, "component": "sentiment_agent", "ticker": "B", "message": "SSLError"},
        {"timestamp": now, "component": "macro_agent", "ticker": None, "message": "HTTP 404"},
    ]
    result = summarize_errors(entries, since_hours=24)
    assert result["categories"]["SSL/TLS transient"]["count"] == 2
    assert result["categories"]["Symbol not supported (404)"]["count"] == 1


def test_summarize_errors_includes_remediation_text():
    now = datetime.utcnow()
    entries = [{"timestamp": now, "component": "sentiment_agent", "ticker": "A", "message": "HTTP 401"}]
    result = summarize_errors(entries, since_hours=24)
    remediation = result["categories"]["Blocked / rate-limited (403/401)"]["remediation"]
    assert len(remediation) > 0
    assert "Reddit" in remediation or "credentials" in remediation.lower()


def test_summarize_errors_empty_input():
    result = summarize_errors([], since_hours=24)
    assert result["total_errors"] == 0
    assert result["categories"] == {}


def test_log_error_never_raises_without_db():
    # No Postgres in this test environment - must not raise, just print
    # and silently skip the DB write.
    log_error("test_component", "test message", ticker="TEST")
    assert True  # if log_error raised, this line is never reached
