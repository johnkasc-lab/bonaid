"""
tests/test_supervisor.py
Tests each of the Supervisor's reconciliation rule branches in isolation -
pure function, no I/O, no dependency on News/Sentiment/Technical actually
running.
"""
from bonaid.agents.supervisor import reconcile

NEUTRAL_NEWS = {"sentiment_label": "Neutral", "sentiment_score": 0.0}
NEUTRAL_SOCIAL = {"sentiment_label": "Neutral", "sentiment_score": 0.0}


def test_buy_downgraded_when_news_bearish():
    decision = reconcile(
        "TEST",
        {"action": "BUY", "confidence": 80.0},
        {"sentiment_label": "Negative", "sentiment_score": -40.0},
        NEUTRAL_SOCIAL,
    )
    assert decision.action == "WATCH"
    assert decision.overridden is True
    assert decision.confidence < 80.0


def test_buy_downgraded_when_only_sentiment_bearish():
    # Either channel alone is enough to trigger caution on a BUY.
    decision = reconcile(
        "TEST",
        {"action": "BUY", "confidence": 80.0},
        NEUTRAL_NEWS,
        {"sentiment_label": "Negative", "sentiment_score": -50.0},
    )
    assert decision.action == "WATCH"
    assert decision.overridden is True


def test_hold_not_upgraded_when_only_one_channel_bullish():
    # Upgrading requires BOTH News and Sentiment - one alone isn't enough.
    decision = reconcile(
        "TEST",
        {"action": "HOLD", "confidence": 30.0},
        {"sentiment_label": "Positive", "sentiment_score": 40.0},
        NEUTRAL_SOCIAL,
    )
    assert decision.action == "HOLD"
    assert decision.overridden is False


def test_hold_upgraded_when_both_channels_bullish():
    decision = reconcile(
        "TEST",
        {"action": "HOLD", "confidence": 30.0},
        {"sentiment_label": "Positive", "sentiment_score": 40.0},
        {"sentiment_label": "Positive", "sentiment_score": 60.0},
    )
    assert decision.action == "WATCH"
    assert decision.overridden is True
    assert decision.action != "BUY"  # never manufactures a BUY from sentiment alone


def test_buy_unchanged_when_channels_bullish_or_neutral():
    decision = reconcile(
        "TEST",
        {"action": "BUY", "confidence": 75.0},
        {"sentiment_label": "Positive", "sentiment_score": 30.0},
        NEUTRAL_SOCIAL,
    )
    assert decision.action == "BUY"
    assert decision.overridden is False
    assert decision.confidence == 75.0


def test_sell_unchanged_regardless_of_sentiment():
    decision = reconcile(
        "TEST",
        {"action": "SELL", "confidence": 10.0},
        NEUTRAL_NEWS,
        NEUTRAL_SOCIAL,
    )
    assert decision.action == "SELL"
    assert decision.overridden is False


def test_mixed_sentiment_does_not_trigger_override():
    decision = reconcile(
        "TEST",
        {"action": "BUY", "confidence": 60.0},
        {"sentiment_label": "Mixed", "sentiment_score": 0.0},
        {"sentiment_label": "Mixed", "sentiment_score": 0.0},
    )
    assert decision.action == "BUY"
    assert decision.overridden is False


def test_decision_always_includes_reasoning():
    decision = reconcile(
        "TEST",
        {"action": "WATCH", "confidence": 50.0},
        {"sentiment_label": "No Data", "sentiment_score": 0.0},
        {"sentiment_label": "No Data", "sentiment_score": 0.0},
    )
    assert len(decision.reasoning) >= 1
    assert isinstance(decision.reasoning[0], str)
