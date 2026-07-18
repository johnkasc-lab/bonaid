"""
bonaid/cache.py
Redis wrapper. Two jobs in this architecture:
  1. Caching (e.g. latest price data, avoid hammering data providers)
  2. Pub/Sub message bus between agents in later phases (the Supervisor
     publishes tasks, agents subscribe and publish results back) - Redis
     pub/sub is a free, simple, battle-tested way to do this without
     standing up Kafka/RabbitMQ.
"""
import json
from typing import Any, Optional
import redis

from bonaid.config import settings

_client: Optional[redis.Redis] = None


def get_redis() -> redis.Redis:
    global _client
    if _client is None:
        _client = redis.from_url(settings.redis_url, decode_responses=True)
    return _client


def cache_set(key: str, value: Any, ttl_seconds: int = 300) -> bool:
    """Returns True on success, False if Redis is unreachable - never
    raises. Caching is a performance optimization; a Redis outage should
    degrade to 'no caching', not crash whatever called this."""
    try:
        get_redis().set(key, json.dumps(value), ex=ttl_seconds)
        return True
    except Exception as e:
        print(f"[cache] set failed (Redis unavailable?): {e}")
        return False


def cache_get(key: str) -> Any:
    """Returns the cached value, or None on a cache miss OR if Redis is
    unreachable - callers can't distinguish the two, which is correct
    here: either way, the answer is 'go compute it fresh', never a crash."""
    try:
        raw = get_redis().get(key)
        return json.loads(raw) if raw is not None else None
    except Exception as e:
        print(f"[cache] get failed (Redis unavailable?): {e}")
        return None


def publish(channel: str, message: dict):
    get_redis().publish(channel, json.dumps(message))


def ping() -> bool:
    try:
        return get_redis().ping()
    except Exception:
        return False
