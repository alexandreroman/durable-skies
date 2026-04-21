"""Fleet-level activities.

Thin wrappers that let workflows write to Redis without breaking determinism.
Workflows must not import `events` directly (Redis I/O is side-effectful);
they call `log_fleet_event` as a *local* activity so the overhead is a single
marker event in history instead of three for a full activity.
"""

from __future__ import annotations

from temporalio import activity

from ..events import write_fleet_event
from ..models import FleetEvent


@activity.defn
async def log_fleet_event(event: FleetEvent) -> None:
    await write_fleet_event(event)
