"""Drone control activities.

Each activity simulates a physical action. State flows split by durability
needs:

- Business state (state-enum transitions, advance_leg, signals): pushed back
  to the per-drone entity workflow via `update_runtime` / `advance_leg`.
- Live telemetry (position, battery, target_point_id): written to Redis per
  nav step. The FastAPI gateway merges it into `/fleet`. Redis is best-effort —
  a failed write never breaks a mission.
- Fleet event log (takeoff/pickup/delivery notifications): written directly
  to Redis via `write_fleet_event`. Same best-effort contract.

The ADK pilot agent (running inside the per-delivery workflow) invokes these
activities through `activity_tool`.
"""

import asyncio
import uuid
from datetime import UTC, datetime

from pydantic import ValidationError
from temporalio import activity
from temporalio.exceptions import ApplicationError

from ..events import write_fleet_event
from ..models import Coordinate, FleetEvent, FleetEventType, WorkflowState
from ..telemetry import read_drone_telemetries, write_drone_telemetry
from .drone_signal import advance_leg, update_drone
from .world import resolve_location, resolve_name

_NAV_STEPS = 6
_NAV_STEP_DELAY_S = 2.0
_BATTERY_PER_STEP = 2.0
_BATTERY_CRITICAL_PCT = 25.0


def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def _event(message: str, event_type: FleetEventType = FleetEventType.INFO) -> FleetEvent:
    return FleetEvent(
        id=uuid.uuid4().hex,
        time=datetime.now(UTC).isoformat(),
        type=event_type,
        message=message,
    )


@activity.defn
async def takeoff_drone(drone_id: str, drone_workflow_id: str) -> str:
    activity.logger.info("Drone %s taking off", drone_id)
    await write_fleet_event(_event(f"🛫 {drone_id} takeoff"))
    await asyncio.sleep(1.5)
    await update_drone(drone_workflow_id, state=WorkflowState.IN_FLIGHT)
    await advance_leg(drone_workflow_id)
    return f"Drone {drone_id} is airborne"


@activity.defn
async def land_drone(drone_id: str, drone_workflow_id: str) -> str:
    activity.logger.info("Drone %s landing", drone_id)
    await write_fleet_event(_event(f"🛬 {drone_id} landing"))
    await asyncio.sleep(1.0)
    await advance_leg(drone_workflow_id)
    return f"Drone {drone_id} has landed"


@activity.defn
async def navigate_drone(
    drone_id: str,
    from_point_id: str,
    to_point_id: str,
    drone_workflow_id: str,
    kind: str,
    battery_start_pct: float = 100.0,
) -> float:
    """Interpolates a drone from `from_point_id` to `to_point_id`.

    `kind` is "to_target" or "returning" and maps to the workflow state reported
    during the flight. Returns the final battery percentage.

    Position/battery are streamed to Redis (telemetry); only the battery-critical
    incident is signaled back to the drone workflow. If the battery dips below
    the critical threshold during the first half of a "to_target" trip, the
    activity injects an incident and raises a non-retryable `ApplicationError`
    so the calling workflow can run its compensation saga.
    """
    start = resolve_location(from_point_id)
    end = resolve_location(to_point_id)
    in_flight_state = WorkflowState.RETURNING if kind == "returning" else WorkflowState.IN_FLIGHT

    battery = battery_start_pct

    for step in range(1, _NAV_STEPS + 1):
        progress = step / _NAV_STEPS
        position = Coordinate(
            lat=_lerp(start.lat, end.lat, progress),
            lon=_lerp(start.lon, end.lon, progress),
        )
        battery = max(0.0, battery - _BATTERY_PER_STEP)

        await write_drone_telemetry(
            drone_id,
            position=position,
            battery_pct=battery,
            target_point_id=to_point_id,
            state=in_flight_state,
        )
        activity.heartbeat(progress)

        # Inject a one-shot battery incident during the outbound half of a delivery.
        if kind == "to_target" and progress < 0.5 and battery < _BATTERY_CRITICAL_PCT:
            await write_drone_telemetry(
                drone_id,
                position=position,
                battery_pct=battery,
                target_point_id=to_point_id,
                state=WorkflowState.INCIDENT,
            )
            await update_drone(
                drone_workflow_id,
                state=WorkflowState.INCIDENT,
                battery_pct=battery,
                add_signal="battery_critical",
            )
            await write_fleet_event(
                _event(f"⚠️ {drone_id} battery {battery:.0f}%", FleetEventType.INCIDENT),
            )
            raise ApplicationError("battery_critical", non_retryable=True)

        await asyncio.sleep(_NAV_STEP_DELAY_S)

    await write_fleet_event(_event(f"📍 {drone_id} → {resolve_name(to_point_id)}"))
    await update_drone(drone_workflow_id, battery_pct=battery)
    await advance_leg(drone_workflow_id)
    return battery


@activity.defn
async def read_drone_position(drone_id: str) -> Coordinate | None:
    """Return the drone's last known position from Redis telemetry, or None if unavailable."""
    activity.logger.info("Reading live position for drone %s", drone_id)
    entry = (await read_drone_telemetries([drone_id])).get(drone_id)
    if entry is None:
        return None
    try:
        return Coordinate.model_validate(entry["position"])
    except (KeyError, ValidationError) as err:
        activity.logger.warning("Unusable telemetry for %s: %s", drone_id, err)
        return None


@activity.defn
async def pickup_package(
    drone_id: str,
    order_id: str,
    base_id: str,
    drone_workflow_id: str,
) -> str:
    activity.logger.info("Drone %s picking up order %s at %s", drone_id, order_id, base_id)
    await write_fleet_event(
        _event(f"📦 {drone_id} pickup {resolve_name(base_id)}", FleetEventType.SIGNAL),
    )
    await asyncio.sleep(1.0)
    await advance_leg(drone_workflow_id)
    return f"Order {order_id} picked up by {drone_id}"


@activity.defn
async def dropoff_package(
    drone_id: str,
    order_id: str,
    dropoff_point_id: str,
    drone_workflow_id: str,
) -> str:
    activity.logger.info("Drone %s delivering order %s at %s", drone_id, order_id, dropoff_point_id)
    await update_drone(drone_workflow_id, state=WorkflowState.DELIVERING, add_signal="delivered")
    await write_fleet_event(_event(f"✅ {drone_id} delivered", FleetEventType.SUCCESS))
    await asyncio.sleep(1.0)
    await advance_leg(drone_workflow_id)
    return f"Order {order_id} delivered at {dropoff_point_id}"
