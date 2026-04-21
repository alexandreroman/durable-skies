"""Fleet workflow: long-running supervisor for the drone fleet.

Accepts orders and routes each to a per-drone entity workflow (`DroneWorkflow`).
The fleet no longer maintains any drone registry of its own — it reads a fresh
availability snapshot from Redis (`fleet:availability`, written by each
`DroneWorkflow` on state transitions) at every dispatch cycle. This makes the
fleet quasi-stateless w.r.t. drones and keeps its event history small.

The fleet event log (takeoff/pickup/incident notifications) is written to
Redis through the `log_fleet_event` local activity — see `..events`.

Order-to-drone assignment is delegated to an ADK dispatcher agent (see
`..agents.dispatcher`). A round-robin picker — rebuilt from the sorted list
of drone ids returned by Redis at each dispatch — is the deterministic
fallback when the agent fails or returns an invalid choice.
"""

import json
from collections import deque
from datetime import timedelta

from google.adk.runners import InMemoryRunner
from google.genai import types
from temporalio import workflow

with workflow.unsafe.imports_passed_through():
    from ..agents import DISPATCH_DECISION_KEY, build_dispatcher_agent

from .. import drone_workflow_id, order_workflow_id
from ..activities import log_fleet_event, read_drone_availabilities_activity
from ..models import (
    DroneAvailability,
    FleetEvent,
    FleetEventType,
    FleetState,
    Order,
    WorkflowState,
)
from ..world import DELIVERY_POINTS, DEPOTS

_HISTORY_THRESHOLD = 2000
_MIN_DISPATCH_BATTERY_PCT = 40.0
_LOG_EVENT_TIMEOUT = timedelta(seconds=5)
_READ_AVAILABILITY_TIMEOUT = timedelta(seconds=5)


@workflow.defn
class FleetWorkflow:
    def __init__(self) -> None:
        self._pending: deque[Order] = deque()
        self._shutdown = False
        self._model_name: str | None = None
        self._fast_model_name: str | None = None
        self._dispatching: bool = False
        self._waiting_for_drone: bool = False

    @workflow.run
    async def run(
        self,
        model_name: str,
        initial_pending: list[Order] | None = None,
        fast_model_name: str | None = None,
    ) -> None:
        self._model_name = model_name
        self._fast_model_name = fast_model_name
        if initial_pending is not None:
            self._pending = deque(initial_pending)
        workflow.logger.info("FleetWorkflow started")
        while not self._shutdown:
            if not self._pending and workflow.info().get_current_history_length() > _HISTORY_THRESHOLD:
                workflow.continue_as_new(
                    args=[
                        self._model_name,
                        list(self._pending),
                        self._fast_model_name,
                    ],
                )
            await workflow.wait_condition(lambda: bool(self._pending) or self._shutdown)
            if self._shutdown:
                return

            order = self._pending[0]
            availabilities = await self._read_availabilities()
            dispatchable = [a for a in availabilities if self._is_dispatchable(a)]
            if not dispatchable:
                # Redis empty or no candidates: poll quietly and retry. We can't
                # await a fleet-wide "drone became idle" signal anymore (no local
                # registry), so the dispatcher polls Redis on a sleep timer. The
                # order stays on the pending queue the whole time.
                if not self._waiting_for_drone:
                    await self._log_event(
                        "⌛ Waiting for drone",
                        FleetEventType.INFO,
                    )
                    self._waiting_for_drone = True
                await workflow.sleep(timedelta(seconds=2))
                continue
            self._waiting_for_drone = False

            # Flag is scoped tightly around the LLM call so the UI only flashes during real agent latency.
            self._dispatching = True
            try:
                drone_id = await self._dispatch_with_agent(order, dispatchable)
            finally:
                self._dispatching = False
            if drone_id is None or not any(a.drone_id == drone_id for a in dispatchable):
                drone_id = self._pick_idle_drone(dispatchable)
            if drone_id is None:
                continue

            # Pop after the dispatcher picks so the UI queue chip stays stable during the agent run.
            self._pending.popleft()
            drone_name = next(a.name for a in dispatchable if a.drone_id == drone_id)
            await self._log_event(f"📦 {drone_name} dispatched", FleetEventType.SIGNAL)

            drone_handle = workflow.get_external_workflow_handle(drone_workflow_id(drone_id))
            await drone_handle.signal("assign_order", order)
            order_handle = workflow.get_external_workflow_handle(order_workflow_id(order.id))
            await order_handle.signal("mark_assigned")

    async def _read_availabilities(self) -> list[DroneAvailability]:
        """Pull the fresh availability registry from Redis via a local activity."""
        return await workflow.execute_local_activity(
            read_drone_availabilities_activity,
            start_to_close_timeout=_READ_AVAILABILITY_TIMEOUT,
        )

    async def _dispatch_with_agent(
        self,
        order: Order,
        dispatchable: list[DroneAvailability],
    ) -> str | None:
        """Ask the dispatcher agent to pick an idle drone; None means fall back."""
        if self._model_name is None:
            return None

        try:
            agent = build_dispatcher_agent(self._model_name, analyst_model_name=self._fast_model_name)
            runner = InMemoryRunner(agent=agent, app_name="durable-skies")
            session = await runner.session_service.create_session(
                app_name="durable-skies",
                user_id="fleet-dispatcher",
            )

            payload = {
                "order": {
                    "id": order.id,
                    "pickup_base_id": order.pickup_base_id,
                    "dropoff_point_id": order.dropoff_point_id,
                    "payload_kg": order.payload_kg,
                },
                "idle_drones": [
                    {
                        "id": a.drone_id,
                        "name": a.name,
                        "home_base_id": a.home_base_id,
                        "battery_pct": a.battery_pct,
                    }
                    for a in dispatchable
                ],
            }
            prompt = json.dumps(payload)

            async for _ in runner.run_async(
                user_id="fleet-dispatcher",
                session_id=session.id,
                new_message=types.Content(role="user", parts=[types.Part(text=prompt)]),
            ):
                pass

            refreshed = await runner.session_service.get_session(
                app_name="durable-skies",
                user_id="fleet-dispatcher",
                session_id=session.id,
            )
            decision = (refreshed.state or {}).get(DISPATCH_DECISION_KEY, {}) if refreshed else {}
            drone_id = decision.get("drone_id")
            reasoning = decision.get("reasoning", "")

            chosen = next((a for a in dispatchable if a.drone_id == drone_id), None)
            if chosen is None:
                return None

            workflow.logger.info("Dispatcher picked %s: %s", chosen.name, reasoning)
            await self._log_event(f"🤖 Dispatcher → {chosen.name}", FleetEventType.INFO)
            return chosen.drone_id
        except Exception as err:
            # Any failure (LLM error, sandbox hiccup, malformed decision) yields the
            # deterministic round-robin fallback so orders keep flowing.
            workflow.logger.warning("Dispatcher agent failed: %s", err)
            await self._log_event(
                "⚠️ Dispatcher failed, falling back to round-robin",
                FleetEventType.INFO,
            )
            return None

    @workflow.signal
    def submit_order(self, order: Order) -> None:
        self._pending.append(order)

    @workflow.signal
    def shutdown(self) -> None:
        self._shutdown = True

    @workflow.query
    def get_fleet_state(self) -> FleetState:
        # Drones are assembled by the API layer from per-drone queries; the fleet
        # query no longer owns the registry. `events` comes from Redis too.
        return FleetState(
            drones=[],
            bases=list(DEPOTS),
            delivery_points=list(DELIVERY_POINTS),
            events=[],
            pending_orders_count=len(self._pending),
            dispatching=self._dispatching,
            dispatchable_drones_count=0,
        )

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

    def _is_dispatchable(self, a: DroneAvailability) -> bool:
        return a.state == WorkflowState.IDLE and a.battery_pct > _MIN_DISPATCH_BATTERY_PCT and not a.paused

    def _pick_idle_drone(self, dispatchable: list[DroneAvailability]) -> str | None:
        """Deterministic fallback: first candidate by sorted drone_id.

        The sort makes the choice reproducible under replay (Redis returns hash
        fields in insertion order, which is not stable across rewrites). Round-
        robin fairness is no longer threaded across deliveries — with a stateless
        fleet it would require extra Redis state for marginal benefit.
        """
        if not dispatchable:
            return None
        return sorted(dispatchable, key=lambda a: a.drone_id)[0].drone_id
