"""Redis-backed drone availability registry.

Each `DroneWorkflow` publishes its eligibility-impacting state to Redis on every
state transition; `FleetWorkflow`'s dispatcher reads the aggregate snapshot at
dispatch time. This keeps the fleet singleton stateless w.r.t. the drone list —
the registry no longer lives in workflow history — and mirrors the split used
for telemetry (`telemetry.py`) and the event log (`events.py`).

Entries carry an `updated_at` ISO-8601 timestamp retained purely as
observability metadata, so a human inspecting the Redis hash can see when each
drone last changed state. Readers do not filter on it: because writes only
happen on state transitions, a drone that sits IDLE indefinitely would
otherwise disappear from the dispatch pool. On any Redis error the writer logs
and swallows — a failed availability write must never break a mission.
"""

from __future__ import annotations

import json
import logging

from pydantic import ValidationError
from redis.exceptions import RedisError

from .models import DroneAvailability
from .redis_client import get_redis_client

log = logging.getLogger("durable_skies.availability")

_AVAILABILITY_KEY = "fleet:availability"


async def write_drone_availability(availability: DroneAvailability) -> None:
    """Upsert a drone's availability entry in the fleet registry hash.

    Swallows all Redis errors: losing a registry write is recoverable (the next
    state transition rewrites it, and stale entries age out on read), but
    propagating the error would fail the activity that signals into this
    function from workflow code.
    """
    payload = availability.model_dump_json()
    try:
        client = await get_redis_client()
        await client.hset(_AVAILABILITY_KEY, availability.drone_id, payload)
    except (RedisError, OSError) as err:
        log.warning("Failed to write availability for %s: %s", availability.drone_id, err)


async def read_drone_availabilities() -> list[DroneAvailability]:
    """Return every drone availability entry stored in the fleet registry hash.

    The full hash is returned unfiltered; only corrupt entries (invalid JSON or
    failing Pydantic validation) are skipped and logged. Returns an empty list
    on any Redis error — the caller defers dispatch and keeps orders pending.
    """
    try:
        client = await get_redis_client()
        raw = await client.hgetall(_AVAILABILITY_KEY)
    except (RedisError, OSError) as err:
        log.warning("Failed to read availability: %s", err)
        return []

    entries: list[DroneAvailability] = []
    for drone_id, blob in raw.items():
        try:
            entry = DroneAvailability.model_validate(json.loads(blob))
        except (json.JSONDecodeError, ValidationError) as err:
            log.warning("Corrupt availability for %s: %s", drone_id, err)
            continue
        entries.append(entry)
    return entries
