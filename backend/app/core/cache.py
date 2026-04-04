"""Async Redis cache layer.

Provides JSON get/set/delete with TTL and key prefixing.
Uses the same Redis instance as Celery (keys are namespaced by prefix).
"""

from __future__ import annotations

import json
from typing import Any

import redis.asyncio as aioredis
from loguru import logger

from app.config import settings

PREFIX = "nutri:"

_pool: aioredis.Redis | None = None


async def get_redis() -> aioredis.Redis:
    """Return a shared async Redis connection pool (singleton)."""
    global _pool
    if _pool is None:
        _pool = aioredis.from_url(
            settings.REDIS_URL,
            decode_responses=True,
        )
    return _pool


async def get_json(key: str) -> Any | None:
    """Get a JSON-serialized value from cache. Returns None on miss."""
    r = await get_redis()
    raw = await r.get(f"{PREFIX}{key}")
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        logger.warning("Cache: invalid JSON for key {}", key)
        return None


async def set_json(key: str, value: Any, ttl: int = 3600) -> None:
    """Store a JSON-serializable value in cache with TTL (seconds)."""
    r = await get_redis()
    raw = json.dumps(value, ensure_ascii=False, default=str)
    await r.set(f"{PREFIX}{key}", raw, ex=ttl)


async def delete(key: str) -> None:
    """Delete a key from cache."""
    r = await get_redis()
    await r.delete(f"{PREFIX}{key}")


async def close() -> None:
    """Close the Redis connection pool. Call on app shutdown."""
    global _pool
    if _pool is not None:
        await _pool.aclose()
        _pool = None
