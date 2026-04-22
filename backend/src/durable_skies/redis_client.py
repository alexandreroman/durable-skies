"""Shared lazy Redis client used by telemetry, events, and availability.

All three modules talk to the same Redis URL; a single pooled client is enough
and keeps connection management in one place. On any Redis error callers log
and swallow — none of those code paths may break a mission.
"""

from __future__ import annotations

import asyncio
import logging

import redis.asyncio as redis
from redis.exceptions import RedisError

from .config import get_settings

log = logging.getLogger("durable_skies.redis_client")

_client: redis.Redis | None = None
_client_lock = asyncio.Lock()


async def get_redis_client() -> redis.Redis:
    """Return a process-wide Redis client, creating it on first use."""
    global _client
    if _client is not None:
        return _client
    async with _client_lock:
        if _client is None:
            settings = get_settings()
            _client = redis.from_url(settings.redis_url, decode_responses=True)
    return _client


async def close_redis_client() -> None:
    """Close the shared client (idempotent); called from the API lifespan."""
    global _client
    if _client is None:
        return
    try:
        await _client.aclose()
    except (RedisError, OSError) as err:
        log.warning("Error closing Redis client: %s", err)
    finally:
        _client = None
