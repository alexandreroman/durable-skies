"""Fleet workflow: long-running supervisor for the drone fleet.

Owns the canonical runtime state of the fleet (drones + event log), exposes it
to the FastAPI layer through a query, and dispatches every incoming order to a
`DroneDeliveryWorkflow` child. Children signal back with drone updates and
event-log entries so the workflow stays the single source of truth for the UI.
"""

from collections import deque
from typing import Any

from temporalio import workflow

from .. import TASK_QUEUE
from ..models import (
    Coordinate,
    DroneRuntimeState,
    FleetEvent,
    FleetEventType,
    FleetState,
    Order,
    WorkflowState,
)
from ..world import DELIVERY_POINTS, DEPOTS, initial_drones
from .drone import DroneDeliveryWorkflow

MAX_EVENTS = 40


@workflow.defn
class FleetWorkflow:
    def __init__(self) -> None:
        self._drones: dict[str, DroneRuntimeState] = {d.id: d for d in initial_drones()}
        self._drone_order: list[str] = list(self._drones.keys())
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
            delivery_workflow_id = f"delivery-{order.id}"
            drone.state = WorkflowState.DISPATCHED
            drone.current_order_id = order.id
            drone.workflow_id = delivery_workflow_id
            drone.target_point_id = order.pickup_base_id
            drone.signals = ["dispatched"]

            self._append_event(
                FleetEventType.SIGNAL,
                f"📦 {drone.name} dispatched",
            )

            # Fire-and-forget: start the child and move on so the supervisor can
            # accept more orders while deliveries run in parallel.
            await workflow.start_child_workflow(
                DroneDeliveryWorkflow.run,
                args=[workflow.info().workflow_id, drone_id, drone.home_base_id, order, model_name],
                id=delivery_workflow_id,
                task_queue=TASK_QUEUE,
                parent_close_policy=workflow.ParentClosePolicy.ABANDON,
            )

    @workflow.signal
    def submit_order(self, order: Order) -> None:
        self._pending.append(order)

    @workflow.signal
    def shutdown(self) -> None:
        self._shutdown = True

    @workflow.signal
    def update_drone(self, update: dict[str, Any]) -> None:
        """Merge a partial drone update coming from an activity."""
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
        if update.get("clear_signals"):
            drone.signals = []
        if update.get("add_signal"):
            sig = update["add_signal"]
            if sig not in drone.signals:
                drone.signals = [*drone.signals, sig]

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
