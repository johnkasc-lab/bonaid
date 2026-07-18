"""
synthetic_data.py
FOR VALIDATION ONLY. Generates realistic-ish 5-year daily OHLCV series
(regime-switching geometric Brownian motion + volatility clustering) so the
backtest engine can be proven correct in environments without live internet
access (e.g. this sandbox). Replace with data_fetcher.py for real trading use.
"""
import numpy as np
import pandas as pd


def _generate_price_path(n_days: int, seed: int, start_price: float = 100.0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    # .normalize() strips the time component - without it, pandas 3.0's
    # bdate_range(end=Timestamp.today(), periods=n) can intermittently
    # return n-1 dates depending on the current time of day (a pandas 3.0
    # behavior change). That mismatch used to surface as a random
    # DataFrame-construction ValueError, only on certain days/times -
    # exactly the kind of bug that's hard to reproduce on demand.
    dates = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=n_days)
    n_days = len(dates)  # use the ACTUAL count from here on, in case it still differs

    # Regime-switching drift/vol (bull / bear / choppy) to give strategies
    # something realistic to differentiate on.
    regimes = rng.choice([0, 1, 2], size=n_days, p=[0.55, 0.15, 0.30])
    drift_map = {0: 0.0006, 1: -0.0012, 2: 0.0001}
    vol_map = {0: 0.011, 1: 0.022, 2: 0.016}

    log_returns = np.array([rng.normal(drift_map[r], vol_map[r]) for r in regimes])
    close = start_price * np.exp(np.cumsum(log_returns))

    daily_range = np.abs(rng.normal(0.01, 0.004, n_days)) * close
    high = close + daily_range * rng.uniform(0.3, 1.0, n_days)
    low = close - daily_range * rng.uniform(0.3, 1.0, n_days)
    open_ = low + (high - low) * rng.uniform(0.2, 0.8, n_days)
    volume = rng.integers(1_000_000, 20_000_000, n_days)

    df = pd.DataFrame({
        "Open": open_, "High": high, "Low": low, "Close": close, "Volume": volume,
    }, index=dates)
    df.index.name = "Date"
    return df


def generate_universe(tickers: list, years: int = 5) -> dict:
    n_days = years * 252
    data = {}
    for i, t in enumerate(tickers):
        data[t] = _generate_price_path(n_days, seed=42 + i, start_price=float(50 + i * 30))
        print(f"[SYNTH] {t}: {len(data[t])} rows generated")
    return data
