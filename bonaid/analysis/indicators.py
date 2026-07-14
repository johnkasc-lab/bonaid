"""
indicators.py
Pure pandas/numpy technical indicators - no TA-Lib dependency needed (avoids
C-build headaches), fully open source, fast, vectorized.
"""
import numpy as np
import pandas as pd


def sma(series: pd.Series, window: int) -> pd.Series:
    return series.rolling(window).mean()


def ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


def rsi(series: pd.Series, window: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / window, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / window, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def macd(series: pd.Series, fast=12, slow=26, signal=9):
    macd_line = ema(series, fast) - ema(series, slow)
    signal_line = ema(macd_line, signal)
    hist = macd_line - signal_line
    return macd_line, signal_line, hist


def bollinger_bands(series: pd.Series, window: int = 20, num_std: float = 2.0):
    mid = sma(series, window)
    std = series.rolling(window).std()
    upper = mid + num_std * std
    lower = mid - num_std * std
    return upper, mid, lower


def atr(df: pd.DataFrame, window: int = 14) -> pd.Series:
    high, low, close = df["High"], df["Low"], df["Close"]
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / window, adjust=False).mean()


def donchian_channel(df: pd.DataFrame, window: int = 20):
    upper = df["High"].rolling(window).max()
    lower = df["Low"].rolling(window).min()
    return upper, lower


def stochastic_oscillator(df: pd.DataFrame, k_window=14, d_window=3):
    low_min = df["Low"].rolling(k_window).min()
    high_max = df["High"].rolling(k_window).max()
    k = 100 * (df["Close"] - low_min) / (high_max - low_min)
    d = k.rolling(d_window).mean()
    return k, d


def vwap(df: pd.DataFrame) -> pd.Series:
    typical = (df["High"] + df["Low"] + df["Close"]) / 3
    return (typical * df["Volume"]).cumsum() / df["Volume"].cumsum()


def momentum(series: pd.Series, window: int = 10) -> pd.Series:
    return series.diff(window)


def rate_of_change(series: pd.Series, window: int = 10) -> pd.Series:
    return series.pct_change(window) * 100
