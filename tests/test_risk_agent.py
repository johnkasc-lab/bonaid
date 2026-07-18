"""
tests/test_risk_agent.py
Risk Agent never had a dedicated test file before, despite being core
position-sizing logic - this fills that gap, including a regression test
for the entry_price rounding bug found during live testing (was showing
raw float precision like $754.8099975585938 instead of $754.81).
"""
import numpy as np
import pandas as pd
from bonaid.agents.risk_agent import assess_risk


def _make_df(n=300, seed=1, start=100.0, drift=0.1, vol=1.0):
    # .normalize() strips the time component - without it, pandas 3.0's
    # bdate_range(end=Timestamp.today(), periods=n) can return n-1 dates
    # instead of n, depending on the current time of day (a pandas 3.0
    # behavior change, not present in earlier versions).
    dates = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=n)
    close = start + np.cumsum(np.random.default_rng(seed).normal(drift, vol, len(dates)))
    return pd.DataFrame({
        "Open": close, "High": close * 1.01, "Low": close * 0.99,
        "Close": close, "Volume": np.full(len(dates), 1_000_000),
    }, index=dates)


def test_non_buy_action_never_sizes_a_position():
    df = _make_df()
    for action in ["SELL", "HOLD", "WATCH"]:
        risk = assess_risk("TEST", df, action=action, confidence=80.0, capital=100_000)
        assert risk.tradeable is False
        assert risk.position_shares == 0


def test_buy_action_sizes_a_position():
    df = _make_df()
    risk = assess_risk("TEST", df, action="BUY", confidence=80.0, capital=100_000)
    assert risk.tradeable is True
    assert risk.position_shares > 0


def test_entry_price_is_rounded_to_two_decimals():
    # Regression test for the bug found in live testing: entry_price was
    # showing raw float precision (e.g. $754.8099975585938) because it
    # wasn't rounded like stop_loss/take_profit were.
    df = _make_df()
    risk = assess_risk("TEST", df, action="BUY", confidence=80.0, capital=100_000)
    # A price rounded to 2dp, when re-rounded, must equal itself.
    assert risk.entry_price == round(risk.entry_price, 2)


def test_stop_loss_below_entry_and_take_profit_above():
    df = _make_df()
    risk = assess_risk("TEST", df, action="BUY", confidence=80.0, capital=100_000)
    assert risk.stop_loss < risk.entry_price < risk.take_profit


def test_higher_confidence_risks_more_of_the_budget():
    df = _make_df()
    low_conf = assess_risk("TEST", df, action="BUY", confidence=20.0, capital=100_000)
    high_conf = assess_risk("TEST", df, action="BUY", confidence=95.0, capital=100_000)
    assert high_conf.risk_amount >= low_conf.risk_amount


def test_position_never_exceeds_max_position_pct_of_capital():
    df = _make_df(vol=0.1)  # low volatility -> tight stop -> risk math alone would oversize
    risk = assess_risk("TEST", df, action="BUY", confidence=100.0, capital=100_000)
    assert risk.position_pct_of_capital <= 10.5  # settings.max_position_pct default (10%) + small rounding tolerance


def test_insufficient_data_does_not_crash():
    # ATR uses an EWM calculation that still produces a value with very
    # little data (rather than requiring a full window) - so this should
    # NOT crash and should still return a valid, well-formed result either
    # way (tradeable or not), rather than raising an exception.
    df = _make_df(n=5)
    risk = assess_risk("TEST", df, action="BUY", confidence=80.0, capital=100_000)
    assert isinstance(risk.tradeable, bool)
    assert risk.stop_loss < risk.entry_price if risk.tradeable else True
