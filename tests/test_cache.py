"""
tests/test_cache.py
Regression tests for a real bug found while building the dashboard:
cache_get/cache_set used to raise when Redis was unreachable, which would
crash anything that called them (the dashboard, in this case) rather than
degrading to "no caching". Fixed at the source in bonaid/cache.py.
"""
from bonaid import cache


def test_cache_get_returns_none_when_redis_unreachable():
    # No Redis in this test environment - must return None, not raise.
    result = cache.cache_get("some:key")
    assert result is None


def test_cache_set_returns_false_when_redis_unreachable():
    result = cache.cache_set("some:key", {"a": 1})
    assert result is False


def test_ping_returns_false_when_redis_unreachable():
    assert cache.ping() is False
