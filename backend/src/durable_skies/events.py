"""Redis-backed fleet event log.

Activities (writers) push `FleetEvent`s to Redis; the FastAPI gateway (reader)
returns them from `GET /fleet`. The event log is pure observability — losing
a line doesn't corrupt business state — so routing it outside Temporal keeps
the singleton `FleetWorkflow` event history bounded.

Events are stored in a capped Redis list (`fleet:events`) via LPUSH + LTRIM,
so the newest entry is always at index 0. On any Redis error the writer logs
and swallows — a failed event-log write must never break a mission.
"""

from __future__ import annotations

import asyncio
import json
import logging

import redis.asyncio as redis
from pydantic import ValidationError
from redis.exceptions import RedisError

from .config import get_settings
from .models import FleetEvent

log = logging.getLogger("durable_skies.events")

_EVENTS_KEY = "fleet:events"
# Matches the previous in-workflow event cap intent (was 40) but widened to 200
# now that Redis absorbs the cost — gives the UI more scroll-back for free.
_MAX_EVENTS = 200

_client: redis.Redis | None = None
_client_lock = asyncio.Lock()


async def get_events_client() -> redis.Redis:
    global _client
    if _client is not None:
        return _client
    async with _client_lock:
        if _client is None:
            settings = get_settings()
            _client = redis.from_url(settings.redis_url, decode_responses=True)
    return _client


async def write_fleet_event(event: FleetEvent) -> None:
    """Append a fleet event to the Redis list, keeping only the newest N.

    Swallows all Redis errors: event-log loss is recoverable (observability
    only), but propagating the error would fail the activity and roll the
    mission back for no business reason.
    """
    payload = event.model_dump_json()
    try:
        client = await get_events_client()
        pipe = client.pipeline()
        pipe.lpush(_EVENTS_KEY, payload)
        pipe.ltrim(_EVENTS_KEY, 0, _MAX_EVENTS - 1)
        await pipe.execute()
    except (RedisError, OSError) as err:
        log.warning("Failed to write fleet event: %s", err)


async def read_fleet_events() -> list[FleetEvent]:
    """Return all stored fleet events, newest first. Empty on any error."""
    try:
        client = await get_events_client()
        raw = await client.lrange(_EVENTS_KEY, 0, -1)
    except (RedisError, OSError) as err:
        log.warning("Failed to read fleet events: %s", err)
        return []

    events: list[FleetEvent] = []
    for blob in raw:
        try:
            events.append(FleetEvent.model_validate(json.loads(blob)))
        except (json.JSONDecodeError, ValidationError) as err:
            log.warning("Corrupt fleet event: %s", err)
    return events


async def close_events_client() -> None:
    global _client
    if _client is None:
        return
    try:
        await _client.aclose()
    except (RedisError, OSError) as err:
        log.warning("Error closing Redis client: %s", err)
    finally:
        _client = None
