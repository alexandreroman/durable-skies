"""Fleet workflow: long-running supervisor for the drone fleet.

Owns the aggregated runtime snapshot (drones + event log), exposes it to the
FastAPI layer through a query, and routes every incoming order to a per-drone
entity workflow (`DroneWorkflow`). Entities signal back with drone updates;
activities signal back with event-log entries. The fleet stays the single
source of truth for the UI while remaining a thin aggregator.
"""

from collections import deque
from typing import Any

from temporalio import workflow

from .. import drone_workflow_id
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


@workflow.defn
class FleetWorkflow:
    def __init__(self) -> None:
        self._drones: dict[str, DroneRuntimeState] = {d.id: d for d in initial_drones()}
        self._drone_order: list[str] = sorted(self._drones.keys())
        self._pending: deque[Order] = deque()
        self._events: deque[FleetEvent] = deque(maxlen=MAX_EVENTS)
        self._next_drone_idx = 0
        self._shutdown = False

    @workflow.run
    async def run(self, model_name: str) -> None:
        workflow.logger.info("FleetWorkflow started")
        while not self._shutdown:
            await workflow.wait_condition(lambda: bool(self._pending) or self._shutdown)
            if self._shutdown:
                return

            order = self._pending.popleft()
            drone_id = self._pick_idle_drone()
            if drone_id is None:
                # No idle drone — re-queue at head and wait for one to free up.
                self._pending.appendleft(order)
                await workflow.wait_condition(
                    lambda: self._has_idle_drone() or self._shutdown
                )
                continue

            drone = self._drones[drone_id]
            # Optimistically mark the drone as dispatched so the next iteration
            # of the loop doesn't pick it again before the entity has signaled
            # its own state change back.
            drone.state = WorkflowState.DISPATCHED
            drone.current_order_id = order.id
            self._append_event(FleetEventType.SIGNAL, f"📦 {drone.name} dispatched")

            # Hand the order off to the drone entity. The entity runs the
            # DeliveryWorkflow as a child and signals back with state updates.
            drone_handle = workflow.get_external_workflow_handle(drone_workflow_id(drone_id))
            await drone_handle.signal("assign_order", order)

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
        if update.get("clear_signals"):
            drone.signals = []
        if update.get("add_signal"):
            sig = update["add_signal"]
            if sig not in drone.signals:
                drone.signals = [*drone.signals, sig]
        if "signals" in update and update["signals"] is not None:
            drone.signals = list(update["signals"])

    @workflow.signal
    def append_event(self, event: FleetEvent) -> None:
        self._events.appendleft(event)

    @workflow.query
    def get_fleet_state(self) -> FleetState:
        return FleetState(
            drones=[self._drones[d_id] for d_id in sorted(self._drones)],
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

    def _has_idle_drone(self) -> bool:
        return any(d.state == WorkflowState.IDLE for d in self._drones.values())

    def _pick_idle_drone(self) -> str | None:
        n = len(self._drone_order)
        for i in range(n):
            idx = (self._next_drone_idx + i) % n
            drone_id = self._drone_order[idx]
            if self._drones[drone_id].state == WorkflowState.IDLE:
                self._next_drone_idx = (idx + 1) % n
                return drone_id
        return None
