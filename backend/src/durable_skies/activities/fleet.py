"""Fleet-level activities.

Thin wrappers that let workflows write to / read from Redis without breaking
determinism. Workflows must not import Redis modules directly (I/O is
side-effectful); they invoke these as *local* activities so the overhead is a
single marker event in history instead of three for a full activity.
"""

from __future__ import annotations

from temporalio import activity

from ..availability import read_drone_availabilities, write_drone_availability
from ..events import write_fleet_event
from ..models import DroneAvailability, FleetEvent


@activity.defn
async def log_fleet_event(event: FleetEvent) -> None:
    await write_fleet_event(event)


@activity.defn(name="write_drone_availability")
async def write_drone_availability_activity(availability: DroneAvailability) -> None:
    """Publish a drone's availability snapshot to the Redis registry."""
    await write_drone_availability(availability)


@activity.defn(name="read_drone_availabilities")
async def read_drone_availabilities_activity() -> list[DroneAvailability]:
    """Return the fresh availability registry for the dispatcher."""
    return await read_drone_availabilities()
