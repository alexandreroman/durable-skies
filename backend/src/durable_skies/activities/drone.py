"""Drone control activities.

Each activity simulates a physical action, streams updates back to the fleet
workflow via signals, and is wired to the Temporal worker. The ADK agent
(running inside the per-delivery workflow) invokes them through `activity_tool`.
"""

import asyncio

from temporalio import activity
from temporalio.exceptions import ApplicationError

from ..models import Coordinate, FleetEventType, WorkflowState
from .fleet_signal import append_event, update_drone
from .world import resolve_location, resolve_name

_NAV_STEPS = 24
_NAV_STEP_DELAY_S = 0.5
_BATTERY_PER_STEP = 0.5
_BATTERY_CRITICAL_PCT = 25.0


def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


@activity.defn
async def takeoff_drone(drone_id: str, fleet_workflow_id: str) -> str:
    activity.logger.info("Drone %s taking off", drone_id)
    await append_event(fleet_workflow_id, f"🛫 {drone_id} takeoff", FleetEventType.INFO)
    await asyncio.sleep(1.5)
    await update_drone(fleet_workflow_id, drone_id, state=WorkflowState.IN_FLIGHT)
    await append_event(fleet_workflow_id, f"🚁 {drone_id} airborne", FleetEventType.INFO)
    return f"Drone {drone_id} is airborne"


@activity.defn
async def land_drone(drone_id: str, fleet_workflow_id: str) -> str:
    activity.logger.info("Drone %s landing", drone_id)
    await append_event(fleet_workflow_id, f"🛬 {drone_id} landing", FleetEventType.INFO)
    await asyncio.sleep(1.0)
    return f"Drone {drone_id} has landed"


@activity.defn
async def navigate_drone(
    drone_id: str,
    from_point_id: str,
    to_point_id: str,
    fleet_workflow_id: str,
    kind: str,
    battery_start_pct: float = 100.0,
) -> float:
    """Interpolates a drone from `from_point_id` to `to_point_id`.

    `kind` is "to_target" or "returning" and maps to the workflow state reported
    during the flight. Returns the final battery percentage.

    If the battery dips below the critical threshold during the first half of
    a "to_target" trip, the activity injects an incident and raises a
    non-retryable `ApplicationError` so the calling workflow can run its
    compensation saga.
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

        await update_drone(
            fleet_workflow_id,
            drone_id,
            state=in_flight_state,
            position=position,
            battery_pct=battery,
            target_point_id=to_point_id,
        )
        activity.heartbeat(progress)

        # Inject a one-shot battery incident during the outbound half of a delivery.
        if (
            kind == "to_target"
            and progress < 0.5
            and battery < _BATTERY_CRITICAL_PCT
        ):
            await update_drone(
                fleet_workflow_id,
                drone_id,
                state=WorkflowState.INCIDENT,
                add_signal="battery_critical",
            )
            await append_event(
                fleet_workflow_id,
                f"⚠️ {drone_id} battery {battery:.0f}%",
                FleetEventType.INCIDENT,
            )
            await append_event(
                fleet_workflow_id,
                "🤖 Recovery agent → RTB",
                FleetEventType.SIGNAL,
            )
            raise ApplicationError("battery_critical", non_retryable=True)

        await asyncio.sleep(_NAV_STEP_DELAY_S)

    await append_event(
        fleet_workflow_id,
        f"📍 {drone_id} → {resolve_name(to_point_id)}",
        FleetEventType.INFO,
    )
    return battery


@activity.defn
async def pickup_package(
    drone_id: str,
    order_id: str,
    base_id: str,
    fleet_workflow_id: str,
) -> str:
    activity.logger.info("Drone %s picking up order %s at %s", drone_id, order_id, base_id)
    await append_event(
        fleet_workflow_id,
        f"📦 {drone_id} pickup {resolve_name(base_id)}",
        FleetEventType.SIGNAL,
    )
    await asyncio.sleep(1.0)
    await update_drone(fleet_workflow_id, drone_id, add_signal="dispatched")
    return f"Order {order_id} picked up by {drone_id}"


@activity.defn
async def dropoff_package(
    drone_id: str,
    order_id: str,
    dropoff_point_id: str,
    fleet_workflow_id: str,
) -> str:
    activity.logger.info("Drone %s delivering order %s at %s", drone_id, order_id, dropoff_point_id)
    await update_drone(fleet_workflow_id, drone_id, state=WorkflowState.DELIVERING)
    await append_event(
        fleet_workflow_id,
        f"✅ {drone_id} delivered",
        FleetEventType.SUCCESS,
    )
    await asyncio.sleep(1.0)
    await update_drone(fleet_workflow_id, drone_id, add_signal="delivered")
    return f"Order {order_id} delivered at {dropoff_point_id}"


