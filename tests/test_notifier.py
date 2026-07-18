"""
tests/test_notifier.py
Tests graceful degradation when no channels are configured - the default
state in CI/this sandbox, and for any user who hasn't set up alerting yet.
Never makes real network calls (no credentials = no attempt), so this is
safe to run anywhere.
"""
from bonaid.notifier import (
    notify, send_email, send_telegram,
    notify_position_opened, notify_position_closed, notify_exposure_refused,
)


def test_send_email_returns_false_when_unconfigured():
    assert send_email("subject", "body") is False


def test_send_telegram_returns_false_when_unconfigured():
    assert send_telegram("message") is False


def test_notify_returns_both_false_when_unconfigured():
    result = notify("subject", "body")
    assert result == {"email": False, "telegram": False}


def test_notify_never_raises_when_unconfigured():
    # The real point of this test: these should be safe to call
    # unconditionally from trading logic without a try/except at the call
    # site - a notification failure must never break the trade itself.
    notify_position_opened("AAPL", 10, 180.0, 175.0, 190.0, 80.0)
    notify_position_closed("AAPL", 10, 185.0, "take_profit", 50.0)
    notify_exposure_refused("MSFT", 55.0, 50.0)
    # If any of the above raised, this test would fail with an error
    # rather than reaching this assert.
    assert True
