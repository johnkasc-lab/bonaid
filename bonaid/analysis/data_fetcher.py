"""
data_fetcher.py
Free, open-source market data ingestion using yfinance (Yahoo Finance).
Caches to local parquet/csv so 5-year pulls only happen once per ticker.

Run locally (needs internet):  pip install yfinance
"""
import os
import time
import pandas as pd

CACHE_DIR = os.path.join(os.path.dirname(__file__), "data_cache")
os.makedirs(CACHE_DIR, exist_ok=True)


def fetch_ohlcv(ticker: str, years: int = 5, interval: str = "1d", retries: int = 3) -> pd.DataFrame:
    """
    Fetch OHLCV data for `ticker` for the last `years` years.
    Uses local cache if available and fresh.
    Retries on transient network/TLS failures (yfinance's underlying
    curl_cffi client occasionally hits a handshake error, especially from
    inside Docker - this is almost always transient and a retry succeeds).
    Returns DataFrame indexed by date with columns: Open, High, Low, Close, Volume
    """
    cache_path = os.path.join(CACHE_DIR, f"{ticker}_{years}y_{interval}.parquet")
    if os.path.exists(cache_path):
        try:
            return pd.read_parquet(cache_path)
        except Exception:
            pass

    try:
        import yfinance as yf
    except ImportError:
        raise ImportError(
            "yfinance is not installed. Run: pip install yfinance --break-system-packages"
        )

    last_error = None
    for attempt in range(1, retries + 1):
        try:
            df = yf.download(
                ticker,
                period=f"{years}y",
                interval=interval,
                auto_adjust=True,
                progress=False,
            )
            if df.empty:
                raise ValueError(f"No data returned for {ticker}. Check the symbol.")

            if isinstance(df.columns, pd.MultiIndex):
                df.columns = [c[0] for c in df.columns]

            df = df[["Open", "High", "Low", "Close", "Volume"]].dropna()
            df.to_parquet(cache_path)
            return df
        except Exception as e:
            last_error = e
            if attempt < retries:
                wait = attempt * 2  # 2s, 4s backoff
                print(f"[retry] {ticker}: fetch failed ({e}), retrying in {wait}s ({attempt}/{retries})...")
                time.sleep(wait)

    raise RuntimeError(f"Failed to fetch {ticker} after {retries} attempts: {last_error}")


def fetch_universe(tickers: list, years: int = 5, interval: str = "1d") -> dict:
    """Fetch OHLCV for a list of tickers. Returns {ticker: DataFrame}, skips failures."""
    out = {}
    for t in tickers:
        try:
            out[t] = fetch_ohlcv(t, years=years, interval=interval)
            print(f"[OK]   {t}: {len(out[t])} rows")
        except Exception as e:
            print(f"[SKIP] {t}: {e}")
    return out


if __name__ == "__main__":
    # Example universe - edit as needed
    UNIVERSE = ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "SPY"]
    data = fetch_universe(UNIVERSE, years=5)
    print(f"Fetched {len(data)}/{len(UNIVERSE)} tickers.")
