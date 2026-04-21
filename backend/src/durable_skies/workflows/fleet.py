"""Fleet workflow: long-running supervisor for the drone fleet.

Owns the aggregated runtime snapshot (drones + event log), exposes it to the
FastAPI layer through a query, and routes every incoming order to a per-drone
entity workflow (`DroneWorkflow`). Entities signal back with drone updates;
activities signal back with event-log entries. The fleet stays the single
source of truth for the UI while remaining a thin aggregator.

Order-to-drone assignment is delegated to an ADK dispatcher agent (see
`..agents.dispatcher`). A round-robin picker is kept as a deterministic
fallback when the agent fails or returns an invalid choice.
"""

import json
from collections import deque
from typing import Any

from google.adk.runners import InMemoryRunner
from google.genai import types
from temporalio import workflow

with workflow.unsafe.imports_passed_through():
    from ..agents import DISPATCH_DECISION_KEY, build_dispatcher_agent

from .. import drone_workflow_id, order_workflow_id
from ..models import (
    Coordinate,
    DroneRuntimeState,
    FleetEvent,
    FleetEventType,
    FleetState,
    FlightPlan,
    Order,
    WorkflowState,
)
from ..world import DELIVERY_POINTS, DEPOTS, initial_drones

MAX_EVENTS = 40
_HISTORY_THRESHOLD = 2000
_MIN_DISPATCH_BATTERY_PCT = 40.0


@workflow.defn
class FleetWorkflow:
    def __init__(self) -> None:
        self._drones: dict[str, DroneRuntimeState] = {d.id: d for d in initial_drones()}
        self._drone_order: list[str] = sorted(self._drones.keys())
        self._pending: deque[Order] = deque()
        self._events: deque[FleetEvent] = deque(maxlen=MAX_EVENTS)
        self._next_drone_idx = 0
        self._shutdown = False
        self._model_name: str | None = None
        self._fast_model_name: str | None = None

    @workflow.run
    async def run(
        self,
        model_name: str,
        initial_drones: list[DroneRuntimeState] | None = None,
        initial_pending: list[Order] | None = None,
        initial_events: list[FleetEvent] | None = None,
        initial_next_drone_idx: int = 0,
        fast_model_name: str | None = None,
    ) -> None:
        self._model_name = model_name
        self._fast_model_name = fast_model_name
        if initial_drones is not None:
            self._drones = {d.id: d for d in initial_drones}
        if initial_pending is not None:
            self._pending = deque(initial_pending)
        if initial_events is not None:
            self._events = deque(initial_events, maxlen=MAX_EVENTS)
        self._next_drone_idx = initial_next_drone_idx
        workflow.logger.info("FleetWorkflow started")
        while not self._shutdown:
            if (
                not self._pending
                and workflow.info().get_current_history_length() > _HISTORY_THRESHOLD
            ):
                workflow.continue_as_new(
                    args=[
                        self._model_name,
                        [self._drones[d_id] for d_id in self._drone_order],
                        list(self._pending),
                        list(self._events),
                        self._next_drone_idx,
                        self._fast_model_name,
                    ],
                )
            await workflow.wait_condition(lambda: bool(self._pending) or self._shutdown)
            if self._shutdown:
                return

            order = self._pending[0]
            idle_drones = [
                d for d in self._drones.values()
                if d.state == WorkflowState.IDLE and d.battery_pct > _MIN_DISPATCH_BATTERY_PCT
            ]
            if not idle_drones:
                await workflow.wait_condition(
                    lambda: any(
                        d.state == WorkflowState.IDLE and d.battery_pct > _MIN_DISPATCH_BATTERY_PCT
                        for d in self._drones.values()
                    )
                    or self._shutdown
                )
                continue

            drone_id = await self._dispatch_with_agent(order, idle_drones)
            if (
                drone_id is None
                or drone_id not in self._drones
                or self._drones[drone_id].state != WorkflowState.IDLE
            ):
                drone_id = self._pick_idle_drone()
            if drone_id is None:
                continue

            # Pop after the dispatcher picks so the UI queue chip stays stable during the agent run.
            self._pending.popleft()
            drone = self._drones[drone_id]
            drone.state = WorkflowState.DISPATCHED
            drone.current_order_id = order.id
            self._append_event(FleetEventType.SIGNAL, f"📦 {drone.name} dispatched")

            drone_handle = workflow.get_external_workflow_handle(drone_workflow_id(drone_id))
            await drone_handle.signal("assign_order", order)
            order_handle = workflow.get_external_workflow_handle(order_workflow_id(order.id))
            await order_handle.signal("mark_assigned")

    async def _dispatch_with_agent(
        self,
        order: Order,
        idle_drones: list[DroneRuntimeState],
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
                        "id": d.id,
                        "name": d.name,
                        "home_base_id": d.home_base_id,
                        "battery_pct": d.battery_pct,
                        "position": {"lat": d.position.lat, "lon": d.position.lon},
                    }
                    for d in idle_drones
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

            if not drone_id or drone_id not in self._drones:
                return None
            if self._drones[drone_id].state != WorkflowState.IDLE:
                return None

            drone_name = self._drones[drone_id].name
            workflow.logger.info("Dispatcher picked %s: %s", drone_name, reasoning)
            self._append_event(FleetEventType.INFO, f"🤖 Dispatcher → {drone_name}")
            return drone_id
        except Exception as err:
            # Any failure (LLM error, sandbox hiccup, malformed decision) yields the
            # deterministic round-robin fallback so orders keep flowing.
            workflow.logger.warning("Dispatcher agent failed: %s", err)
            self._append_event(
                FleetEventType.INFO,
                "⚠️ Dispatcher failed, falling back to round-robin",
            )
            return None

    @workflow.signal
    def submit_order(self, order: Order) -> None:
        self._pending.append(order)

    @workflow.signal
    def shutdown(self) -> None:
        self._shutdown = True

    @workflow.signal
    def update_drone(self, update: dict[str, Any]) -> None:
        """Merge a partial drone update coming from a `DroneWorkflow`."""
        drone_id = update.get("drone_id")
        if not drone_id or drone_id not in self._drones:
            return
        drone = self._drones[drone_id]

        if "state" in update:
            drone.state = WorkflowState(update["state"])
        if "position" in update and update["position"] is not None:
            drone.position = Coordinate.model_validate(update["position"])
        if "battery_pct" in update:
            drone.battery_pct = float(update["battery_pct"])
        if "workflow_id" in update:
            drone.workflow_id = update["workflow_id"]
        if "current_order_id" in update:
            drone.current_order_id = update["current_order_id"]
        if "target_point_id" in update:
            drone.target_point_id = update["target_point_id"]
        if "flight_plan" in update:
            fp = update["flight_plan"]
            drone.flight_plan = FlightPlan.model_validate(fp) if fp else None
        if "signals" in update and update["signals"] is not None:
            drone.signals = list(update["signals"])

    @workflow.signal
    def append_event(self, event: FleetEvent) -> None:
        self._events.appendleft(event)

    @workflow.query
    def get_fleet_state(self) -> FleetState:
        return FleetState(
            drones=[self._drones[d_id] for d_id in self._drone_order],
            bases=list(DEPOTS),
            delivery_points=list(DELIVERY_POINTS),
            events=list(self._events),
            pending_orders_count=len(self._pending),
        )

    def _append_event(self, event_type: FleetEventType, message: str) -> None:
        self._events.appendleft(
            FleetEvent(
                id=workflow.uuid4().hex,
                time=workflow.now().isoformat(),
                type=event_type,
                message=message,
            )
        )

    def _pick_idle_drone(self) -> str | None:
        n = len(self._drone_order)
        for i in range(n):
            idx = (self._next_drone_idx + i) % n
            drone_id = self._drone_order[idx]
            d = self._drones[drone_id]
            if d.state == WorkflowState.IDLE and d.battery_pct > _MIN_DISPATCH_BATTERY_PCT:
                self._next_drone_idx = (idx + 1) % n
                return drone_id
        return None
