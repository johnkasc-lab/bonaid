"""
strategies.py
Each function takes an OHLCV DataFrame and returns a `signal` Series:
    1  = long / hold long
    0  = flat
   -1  = short / hold short (only used by strategies that short)

All strategies are long-only by default (safer default for equities backtests)
unless marked ALLOW_SHORT.
"""
import numpy as np
import pandas as pd
from bonaid.analysis import indicators as ind


def sma_crossover(df, fast=20, slow=50):
    f, s = ind.sma(df["Close"], fast), ind.sma(df["Close"], slow)
    signal = (f > s).astype(int)
    return signal.fillna(0)


def ema_crossover(df, fast=12, slow=26):
    f, s = ind.ema(df["Close"], fast), ind.ema(df["Close"], slow)
    signal = (f > s).astype(int)
    return signal.fillna(0)


def rsi_mean_reversion(df, window=14, buy_th=30, sell_th=55):
    r = ind.rsi(df["Close"], window)
    signal = pd.Series(0, index=df.index)
    position = 0
    for i in range(len(df)):
        if r.iloc[i] < buy_th:
            position = 1
        elif r.iloc[i] > sell_th:
            position = 0
        signal.iloc[i] = position
    return signal


def macd_trend(df):
    macd_line, signal_line, _ = ind.macd(df["Close"])
    signal = (macd_line > signal_line).astype(int)
    return signal.fillna(0)


def bollinger_breakout(df, window=20, num_std=2.0):
    upper, mid, lower = ind.bollinger_bands(df["Close"], window, num_std)
    signal = pd.Series(0, index=df.index)
    position = 0
    for i in range(len(df)):
        c = df["Close"].iloc[i]
        if pd.isna(upper.iloc[i]):
            continue
        if c > upper.iloc[i]:
            position = 1
        elif c < mid.iloc[i]:
            position = 0
        signal.iloc[i] = position
    return signal


def donchian_breakout(df, window=20):
    upper, lower = ind.donchian_channel(df, window)
    signal = pd.Series(0, index=df.index)
    position = 0
    for i in range(len(df)):
        c = df["Close"].iloc[i]
        if pd.isna(upper.iloc[i]):
            continue
        if c >= upper.iloc[i]:
            position = 1
        elif c <= lower.iloc[i]:
            position = 0
        signal.iloc[i] = position
    return signal


def momentum_strategy(df, window=90, threshold=0.0):
    roc = ind.rate_of_change(df["Close"], window)
    signal = (roc > threshold).astype(int)
    return signal.fillna(0)


def golden_cross_death_cross(df):
    return sma_crossover(df, fast=50, slow=200)


def dual_momentum(df, short_window=20, long_window=100):
    """Combine short and long momentum: only long when both agree."""
    roc_s = ind.rate_of_change(df["Close"], short_window)
    roc_l = ind.rate_of_change(df["Close"], long_window)
    signal = ((roc_s > 0) & (roc_l > 0)).astype(int)
    return signal.fillna(0)


def volatility_breakout_atr(df, window=20, atr_mult=1.5):
    """Enter long on close breaking above prior close + ATR band."""
    a = ind.atr(df, 14)
    upper_band = df["Close"].shift(1) + atr_mult * a
    signal = (df["Close"] > upper_band).astype(int)
    return signal.fillna(0).rolling(3, min_periods=1).max()  # hold a few days


def stochastic_reversal(df, k_window=14, d_window=3, buy_th=20, sell_th=80):
    k, d = ind.stochastic_oscillator(df, k_window, d_window)
    signal = pd.Series(0, index=df.index)
    position = 0
    for i in range(len(df)):
        if pd.isna(k.iloc[i]):
            continue
        if k.iloc[i] < buy_th:
            position = 1
        elif k.iloc[i] > sell_th:
            position = 0
        signal.iloc[i] = position
    return signal


def buy_and_hold(df):
    return pd.Series(1, index=df.index)


# Registry used by main.py to loop over every strategy automatically
STRATEGY_REGISTRY = {
    "SMA_20_50_Crossover": sma_crossover,
    "EMA_12_26_Crossover": ema_crossover,
    "RSI_MeanReversion": rsi_mean_reversion,
    "MACD_Trend": macd_trend,
    "Bollinger_Breakout": bollinger_breakout,
    "Donchian_20_Breakout": donchian_breakout,
    "Momentum_90d": momentum_strategy,
    "Golden_Death_Cross_50_200": golden_cross_death_cross,
    "Dual_Momentum": dual_momentum,
    "ATR_Volatility_Breakout": volatility_breakout_atr,
    "Stochastic_Reversal": stochastic_reversal,
    "Buy_and_Hold": buy_and_hold,
}
