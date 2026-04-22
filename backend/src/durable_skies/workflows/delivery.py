"""Delivery workflow.

One workflow per order. Executes a deterministic activity loop (takeoff →
fly to pickup → pickup → fly to dropoff → dropoff → fly home → land). If any
activity fails, the anomaly handler ADK agent is invoked to pick a recovery
action, and the workflow branches on that choice.

The workflow signals the per-drone entity (`DroneWorkflow`) at each phase
transition; the entity then forwards state to the fleet so the UI (which
polls the fleet) stays in sync. Fleet event-log entries are written to Redis
through the `log_fleet_event` local activity — see `..events`.
"""

import math
from datetime import timedelta

from google.adk.runners import InMemoryRunner
from google.genai import types
from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError, ApplicationError

with workflow.unsafe.imports_passed_through():
    from ..agents import (
        ACTION_ABORT,
        ACTION_DIVERT_RECHARGE,
        ACTION_EMERGENCY_LAND,
        RECOVERY_DECISION_KEY,
        build_anomaly_agent,
    )

from .. import order_workflow_id
from ..activities import (
    dropoff_package,
    fly_drone_to_base,
    land_drone,
    log_fleet_event,
    navigate_drone,
    pickup_package,
    read_drone_telemetry,
    takeoff_drone,
)
from ..models import Coordinate, DroneTelemetrySnapshot, FleetEvent, FleetEventType, Order, WorkflowState
from ..world import DELIVERY_POINTS, DEPOTS

_LOG_EVENT_TIMEOUT = timedelta(seconds=5)


@workflow.defn
class DeliveryWorkflow:
    @workflow.run
    async def run(
        self,
        drone_id: str,
        drone_workflow_id: str,
        home_base_id: str,
        order: Order,
        battery_start_pct: float,
        model_name: str,
    ) -> str:
        drone_handle = workflow.get_external_workflow_handle(drone_workflow_id)

        short = timedelta(seconds=30)
        long = timedelta(minutes=5)
        fast_retry = RetryPolicy(maximum_attempts=3)

        try:
            await workflow.execute_activity(
                takeoff_drone,
                args=[drone_id, drone_workflow_id],
                start_to_close_timeout=short,
                retry_policy=fast_retry,
            )
            order_handle = workflow.get_external_workflow_handle(order_workflow_id(order.id))
            await order_handle.signal("mark_in_progress")
            battery = await workflow.execute_activity(
                navigate_drone,
                args=[
                    drone_id,
                    home_base_id,
                    order.pickup_base_id,
                    drone_workflow_id,
                    "to_target",
                    battery_start_pct,
                ],
                start_to_close_timeout=long,
                heartbeat_timeout=timedelta(seconds=5),
                retry_policy=fast_retry,
            )
            await workflow.execute_activity(
                pickup_package,
                args=[drone_id, order.id, order.pickup_base_id, drone_workflow_id],
                start_to_close_timeout=short,
                retry_policy=fast_retry,
            )
            battery = await workflow.execute_activity(
                navigate_drone,
                args=[
                    drone_id,
                    order.pickup_base_id,
                    order.dropoff_point_id,
                    drone_workflow_id,
                    "to_target",
                    battery,
                ],
                start_to_close_timeout=long,
                heartbeat_timeout=timedelta(seconds=5),
                retry_policy=fast_retry,
            )
            await workflow.execute_activity(
                dropoff_package,
                args=[drone_id, order.id, order.dropoff_point_id, drone_workflow_id],
                start_to_close_timeout=short,
                retry_policy=fast_retry,
            )
            # navigate_drone no longer pushes state per step (it only streams
            # position/battery to Redis), so we mark the RETURNING transition
            # explicitly here.
            await drone_handle.signal("update_runtime", {"state": WorkflowState.RETURNING.value})
            battery = await workflow.execute_activity(
                navigate_drone,
                args=[
                    drone_id,
                    order.dropoff_point_id,
                    home_base_id,
                    drone_workflow_id,
                    "returning",
                    battery,
                ],
                start_to_close_timeout=long,
                heartbeat_timeout=timedelta(seconds=5),
                retry_policy=fast_retry,
            )
            await workflow.execute_activity(
                land_drone,
                args=[drone_id, drone_workflow_id],
                start_to_close_timeout=short,
                retry_policy=fast_retry,
            )
        except (ActivityError, ApplicationError) as err:
            action, snapshot = await self._run_anomaly_handler(drone_id, order, home_base_id, model_name)
            await self._execute_recovery(
                action, drone_handle, drone_id, drone_workflow_id, home_base_id, order, snapshot
            )
            await self._finalize(drone_handle, drone_id, home_base_id, order.id, incident=True)
            return f"Order {order.id} aborted ({action}): {err}"

        await self._finalize(drone_handle, drone_id, home_base_id, order.id, incident=False)
        return f"Order {order.id} completed"

    async def _log_event(self, message: str, event_type: FleetEventType) -> None:
        """Persist a fleet event through the local activity (Redis-backed)."""
        event = FleetEvent(
            id=workflow.uuid4().hex,
            time=workflow.now().isoformat(),
            type=event_type,
            message=message,
        )
        await workflow.execute_local_activity(
            log_fleet_event,
            event,
            start_to_close_timeout=_LOG_EVENT_TIMEOUT,
        )

    async def _run_anomaly_handler(
        self,
        drone_id: str,
        order: Order,
        home_base_id: str,
        model_name: str,
    ) -> tuple[str, DroneTelemetrySnapshot | None]:
        """Invoke the anomaly agent; return a validated recovery action and the drone's live telemetry.

        Any failure inside the agent run falls back to ACTION_ABORT so the
        workflow always has a safe recovery path.
        """
        try:
            snapshot = await workflow.execute_activity(
                read_drone_telemetry,
                drone_id,
                start_to_close_timeout=timedelta(seconds=5),
                retry_policy=RetryPolicy(maximum_attempts=2),
            )
        except (ActivityError, ApplicationError) as err:
            workflow.logger.warning("Failed to read live telemetry for %s: %s", drone_id, err)
            snapshot = None

        try:
            agent = build_anomaly_agent(model_name)
            runner = InMemoryRunner(agent=agent, app_name="durable-skies")
            session = await runner.session_service.create_session(
                app_name="durable-skies",
                user_id=drone_id,
            )

            prompt = self._build_anomaly_prompt(drone_id, order, home_base_id, snapshot)
            async for _ in runner.run_async(
                user_id=drone_id,
                session_id=session.id,
                new_message=types.Content(role="user", parts=[types.Part(text=prompt)]),
            ):
                pass

            refreshed = await runner.session_service.get_session(
                app_name="durable-skies",
                user_id=drone_id,
                session_id=session.id,
            )
            decision = (refreshed.state or {}).get(RECOVERY_DECISION_KEY, {}) if refreshed else {}
            action = decision.get("action", ACTION_ABORT)
            if action not in {ACTION_ABORT, ACTION_EMERGENCY_LAND, ACTION_DIVERT_RECHARGE}:
                action = ACTION_ABORT
        except Exception as err:
            # Safety net: any agent failure (LLM error, sandbox hiccup, malformed decision)
            # falls back to the safest recovery so the workflow always progresses.
            workflow.logger.warning("Anomaly agent failed, defaulting to abort: %s", err)
            action = ACTION_ABORT

        await self._log_event(f"🤖 Recovery agent → {action}", FleetEventType.INFO)
        return action, snapshot

    def _build_anomaly_prompt(
        self,
        drone_id: str,
        order: Order,
        home_base_id: str,
        snapshot: DroneTelemetrySnapshot | None,
    ) -> str:
        base = (
            f"Drone {drone_id} is executing order {order.id} and has raised an in-flight "
            "incident (type: battery_critical). Pick the recovery action that best balances "
            "safety and mission continuity."
        )
        if snapshot is None:
            return base
        position = snapshot.position
        home = next(b.location for b in DEPOTS if b.id == home_base_id)
        nearest_id, _ = self._nearest_base(order, position)
        nearest = next(b.location for b in DEPOTS if b.id == nearest_id)
        d_home = math.hypot(position.lat - home.lat, position.lon - home.lon)
        d_nearest = math.hypot(position.lat - nearest.lat, position.lon - nearest.lon)
        return (
            f"{base}\n"
            f"Live position: lat={position.lat:.4f}, lon={position.lon:.4f}.\n"
            f"Distance to home base: {d_home:.4f}; distance to nearest base: {d_nearest:.4f}."
        )

    async def _execute_recovery(
        self,
        action: str,
        drone_handle,
        drone_id: str,
        drone_workflow_id: str,
        home_base_id: str,
        order: Order,
        snapshot: DroneTelemetrySnapshot | None,
    ) -> None:
        ref = snapshot.position if snapshot else None
        if action == ACTION_ABORT:
            await self._emit_rtb(drone_handle, drone_id, drone_workflow_id, home_base_id, f"↩️ {drone_id} RTB", snapshot)
        elif action == ACTION_EMERGENCY_LAND:
            nearest_id, nearest_name = self._nearest_base(order, ref)
            await self._emit_rtb(
                drone_handle,
                drone_id,
                drone_workflow_id,
                nearest_id,
                f"🛬 {drone_id} emergency landing at {nearest_name}",
                snapshot,
            )
        elif action == ACTION_DIVERT_RECHARGE:
            nearest_id, nearest_name = self._nearest_base(order, ref)
            await self._emit_rtb(
                drone_handle,
                drone_id,
                drone_workflow_id,
                nearest_id,
                f"🔋 {drone_id} diverting to {nearest_name} to recharge",
                snapshot,
            )
            await self._log_event(f"↩️ {drone_id} returning home", FleetEventType.SIGNAL)

    async def _emit_rtb(
        self,
        drone_handle,
        drone_id: str,
        drone_workflow_id: str,
        target_base_id: str,
        event_message: str,
        snapshot: DroneTelemetrySnapshot | None,
        event_type: FleetEventType = FleetEventType.SIGNAL,
    ) -> None:
        await drone_handle.signal("low_battery")
        await self._log_event(event_message, event_type)
        await drone_handle.signal(
            "update_runtime",
            {
                "state": WorkflowState.RETURNING.value,
                "target_point_id": target_base_id,
                "add_signal": "incident",
            },
        )
        if snapshot is not None:
            try:
                await workflow.execute_activity(
                    fly_drone_to_base,
                    args=[drone_id, drone_workflow_id, snapshot.position, target_base_id, snapshot.battery_pct],
                    start_to_close_timeout=timedelta(minutes=5),
                    heartbeat_timeout=timedelta(seconds=5),
                    retry_policy=RetryPolicy(maximum_attempts=3),
                )
            except (ActivityError, ApplicationError) as err:
                # Best-effort: _finalize will still teleport + land so the workflow completes.
                workflow.logger.warning("fly_drone_to_base failed for %s: %s", drone_id, err)
        else:
            await workflow.sleep(timedelta(seconds=2))

    def _nearest_base(self, order: Order, ref: Coordinate | None = None) -> tuple[str, str]:
        """Return the depot closest to `ref` (drone's live position) or, if missing, to the dropoff.

        Live position is preferred so recovery decisions stay accurate when the
        incident happens on the return leg or near pickup. The dropoff-based
        fallback keeps the workflow progressing when telemetry is unavailable.
        """
        if ref is not None:
            ref_lat, ref_lon = ref.lat, ref.lon
        else:
            dropoff = next(dp for dp in DELIVERY_POINTS if dp.id == order.dropoff_point_id)
            ref_lat = dropoff.location.lat
            ref_lon = dropoff.location.lon
        nearest = min(
            DEPOTS,
            key=lambda b: math.hypot(b.location.lat - ref_lat, b.location.lon - ref_lon),
        )
        return (nearest.id, nearest.name)

    async def _finalize(
        self,
        drone_handle,
        drone_id: str,
        home_base_id: str,
        order_id: str,
        *,
        incident: bool,
    ) -> None:
        home_location = next(b.location for b in DEPOTS if b.id == home_base_id)

        await drone_handle.signal(
            "update_runtime",
            {
                "state": WorkflowState.COMPLETED.value,
                "position": home_location.model_dump(),
                "target_point_id": None,
            },
        )
        if not incident:
            await drone_handle.signal("update_runtime", {"add_signal": "delivered"})
        await self._log_event(f"🏠 {drone_id} home ✓", FleetEventType.SUCCESS)

        await workflow.sleep(timedelta(seconds=3))
        await drone_handle.signal(
            "update_runtime",
            {
                "state": WorkflowState.IDLE.value,
                "target_point_id": None,
                "clear_signals": True,
            },
        )

        order_handle = workflow.get_external_workflow_handle(order_workflow_id(order_id))
        message = f"Order {order_id} aborted" if incident else f"Order {order_id} delivered"
        await order_handle.signal("delivery_done", args=[not incident, message])
