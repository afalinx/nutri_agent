"""Async Redis cache layer.

Provides JSON get/set/delete with TTL and key prefixing.
Uses the same Redis instance as Celery (keys are namespaced by prefix).
"""

from __future__ import annotations

import json
import asyncio
from typing import Any

import redis.asyncio as aioredis
from loguru import logger

from app.config import settings

PREFIX = "nutri:"

_clients_by_loop: dict[int, aioredis.Redis] = {}


async def get_redis() -> aioredis.Redis:
    """Return an async Redis client bound to the current event loop.

    redis.asyncio connections are loop-bound. Reusing one global client across
    different Celery task loops causes cross-loop futures and closed-loop errors.
    """
    loop = asyncio.get_running_loop()
    loop_id = id(loop)
    client = _clients_by_loop.get(loop_id)
    if client is None:
        client = aioredis.from_url(
            settings.REDIS_URL,
            decode_responses=True,
        )
        _clients_by_loop[loop_id] = client
    return client


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
    """Close all cached Redis clients. Call on app shutdown."""
    clients = list(_clients_by_loop.values())
    _clients_by_loop.clear()
    for client in clients:
        await client.aclose()
