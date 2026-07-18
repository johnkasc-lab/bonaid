"""
bonaid/universe.py
A diversified universe for `bonaid scan` - spans equities across sectors,
broad-market ETFs, and (since yfinance/data_fetcher handles any ticker
symbol generically, not just equities) a few crypto and forex instruments
too. Edit freely - this is a starting default, not a fixed list.

Grouped by sector so `bonaid scan --sector Healthcare` can filter to just
one group instead of always scanning all ~50.
"""

UNIVERSE = {
    "Technology": ["AAPL", "MSFT", "GOOGL", "NVDA", "META", "AMZN"],
    "Healthcare": ["JNJ", "PFE", "UNH", "MRNA", "LLY"],
    "Aerospace & Defense": ["BA", "LMT", "RTX", "NOC", "GD"],
    "Crypto-Related": ["COIN", "MSTR", "BTC-USD", "ETH-USD"],
    "Currency (Forex)": ["EURUSD=X", "GBPUSD=X", "JPY=X"],
    "Financials": ["JPM", "BAC", "GS", "V", "MA"],
    "Energy": ["XOM", "CVX", "NEE"],
    "Consumer": ["TSLA", "WMT", "COST", "MCD"],
    "Industrials": ["CAT", "GE", "HON"],
    "Broad Market (US)": ["SPY", "QQQ", "DIA", "IWM"],
    "India (NSE)": ["RELIANCE.NS", "TCS.NS", "INFY.NS", "HDFCBANK.NS"],
}


def all_tickers() -> list[str]:
    return [t for tickers in UNIVERSE.values() for t in tickers]


def tickers_for_sector(sector: str) -> list[str]:
    for name, tickers in UNIVERSE.items():
        if name.lower() == sector.lower():
            return tickers
    return []


def sector_of(ticker: str) -> str:
    for name, tickers in UNIVERSE.items():
        if ticker in tickers:
            return name
    return "Unknown"
