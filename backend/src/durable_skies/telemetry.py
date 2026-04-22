"""Redis-backed live telemetry for drone position/battery.

Activities (writers) push per-step position and battery to Redis; the FastAPI
gateway (reader) merges the latest values into `GET /fleet`. This data is pure
telemetry — it doesn't need Temporal durability, and routing it outside of
workflow history keeps DroneWorkflow events bounded.

Every entry carries a short TTL so stale readings expire on their own if a
drone crashes mid-mission. On any Redis error the writer logs and swallows —
a failed telemetry write must never break a mission.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable
from typing import Any

from redis.exceptions import RedisError

from .models import Coordinate, WorkflowState
from .redis_client import get_redis_client

log = logging.getLogger("durable_skies.telemetry")

_TELEMETRY_TTL_S = 10


def _telemetry_key(drone_id: str) -> str:
    return f"drone:{drone_id}:telemetry"


async def write_drone_telemetry(
    drone_id: str,
    position: Coordinate,
    battery_pct: float,
    target_point_id: str | None,
    state: WorkflowState,
) -> None:
    """Write a single drone telemetry entry with a short TTL.

    Swallows all Redis errors: telemetry loss is recoverable (next nav step
    overwrites), but propagating the error would fail the nav activity and
    roll a mission back for no business reason.
    """
    payload = json.dumps(
        {
            "position": position.model_dump(),
            "battery_pct": battery_pct,
            "target_point_id": target_point_id,
            "state": state.value,
        }
    )
    try:
        client = await get_redis_client()
        await client.set(_telemetry_key(drone_id), payload, ex=_TELEMETRY_TTL_S)
    except (RedisError, OSError) as err:
        log.warning("Failed to write telemetry for %s: %s", drone_id, err)


async def read_drone_telemetries(drone_ids: Iterable[str]) -> dict[str, dict[str, Any] | None]:
    """Fetch the latest telemetry for every drone id in a single MGET roundtrip.

    Returns `{drone_id: parsed_dict | None}`. Missing or corrupt entries map to
    None — the caller falls back to the workflow snapshot.
    """
    ids = list(drone_ids)
    if not ids:
        return {}
    try:
        client = await get_redis_client()
        raw = await client.mget(_telemetry_key(did) for did in ids)
    except (RedisError, OSError) as err:
        log.warning("Failed to read telemetry batch: %s", err)
        return dict.fromkeys(ids)

    result: dict[str, dict[str, Any] | None] = {}
    for drone_id, blob in zip(ids, raw, strict=True):
        if blob is None:
            result[drone_id] = None
            continue
        try:
            result[drone_id] = json.loads(blob)
        except json.JSONDecodeError as err:
            log.warning("Corrupt telemetry for %s: %s", drone_id, err)
            result[drone_id] = None
    return result
