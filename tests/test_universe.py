"""
tests/test_universe.py
"""
from bonaid.universe import all_tickers, tickers_for_sector, sector_of, UNIVERSE


def test_all_tickers_nonempty_and_deduped_reasonable():
    tickers = all_tickers()
    assert len(tickers) > 30  # diversified universe, not a tiny list
    assert len(tickers) == len(set(tickers))  # no accidental duplicates across sectors


def test_tickers_for_sector_case_insensitive():
    result = tickers_for_sector("technology")
    assert "AAPL" in result


def test_tickers_for_sector_unknown_returns_empty():
    assert tickers_for_sector("NotARealSector") == []


def test_sector_of_known_ticker():
    assert sector_of("AAPL") == "Technology"


def test_sector_of_unknown_ticker():
    assert sector_of("NOTATICKER") == "Unknown"


def test_universe_covers_multiple_asset_classes():
    # Confirms crypto/forex tickers are genuinely included, not just equities.
    all_t = all_tickers()
    assert any(t.endswith("-USD") for t in all_t)   # crypto
    assert any(t.endswith("=X") for t in all_t)      # forex
    assert any(t.endswith(".NS") for t in all_t)     # India/NSE
