"""Per-drone entity workflow.

One long-lived workflow per physical drone. Owns the drone's runtime state
(position, battery, flight plan) and forwards it to the singleton fleet
workflow for UI aggregation. Each incoming order is executed as a child
`DeliveryWorkflow`; the entity serializes orders — a new one is accepted only
after the current delivery has completed or failed.
"""

import contextlib
from typing import Any

from temporalio import workflow
from temporalio.exceptions import ChildWorkflowError

from .. import TASK_QUEUE
from ..models import (
    Coordinate,
    DroneRuntimeState,
    FlightLeg,
    FlightLegKind,
    FlightLegStatus,
    FlightPlan,
    Order,
    WorkflowState,
)
from .delivery import DeliveryWorkflow


def _build_flight_plan(order: Order, home_base_id: str) -> FlightPlan:
    legs = [
        FlightLeg(kind=FlightLegKind.TAKEOFF, from_point_id=home_base_id, to_point_id=home_base_id),
        FlightLeg(kind=FlightLegKind.TO_PICKUP, from_point_id=home_base_id, to_point_id=order.pickup_base_id),
        FlightLeg(kind=FlightLegKind.PICKUP, from_point_id=order.pickup_base_id, to_point_id=order.pickup_base_id),
        FlightLeg(
            kind=FlightLegKind.TO_DROPOFF,
            from_point_id=order.pickup_base_id,
            to_point_id=order.dropoff_point_id,
        ),
        FlightLeg(
            kind=FlightLegKind.DROPOFF,
            from_point_id=order.dropoff_point_id,
            to_point_id=order.dropoff_point_id,
        ),
        FlightLeg(kind=FlightLegKind.RETURN, from_point_id=order.dropoff_point_id, to_point_id=home_base_id),
        FlightLeg(kind=FlightLegKind.LAND, from_point_id=home_base_id, to_point_id=home_base_id),
    ]
    return FlightPlan(order_id=order.id, legs=legs)


@workflow.defn
class DroneWorkflow:
    def __init__(self) -> None:
        self._drone_id: str | None = None
        self._name: str | None = None
        self._home_base_id: str | None = None
        self._home_location: Coordinate | None = None
        self._fleet_workflow_id: str | None = None

        self._state: WorkflowState = WorkflowState.IDLE
        self._position: Coordinate | None = None
        self._battery_pct: float = 100.0
        self._signals: list[str] = []
        self._target_point_id: str | None = None
        self._flight_plan: FlightPlan | None = None
        self._current_order: Order | None = None
        self._current_delivery_workflow_id: str | None = None
        self._pending_order: Order | None = None
        self._shutdown: bool = False

    @workflow.run
    async def run(
        self,
        drone_id: str,
        name: str,
        home_base_id: str,
        home_location: Coordinate,
        fleet_workflow_id: str,
        model_name: str,
    ) -> None:
        self._drone_id = drone_id
        self._name = name
        self._home_base_id = home_base_id
        self._home_location = home_location
        self._position = home_location.model_copy()
        self._fleet_workflow_id = fleet_workflow_id

        # Push an initial IDLE snapshot so the fleet knows we exist.
        await self._sync_to_fleet()

        while not self._shutdown:
            await workflow.wait_condition(lambda: self._pending_order is not None or self._shutdown)
            if self._shutdown:
                return

            order = self._pending_order
            assert order is not None
            self._pending_order = None
            self._current_order = order
            self._current_delivery_workflow_id = f"delivery-{order.id}"

            self._flight_plan = _build_flight_plan(order, home_base_id)
            self._flight_plan.legs[0].status = FlightLegStatus.ACTIVE
            self._state = WorkflowState.DISPATCHED
            self._signals = ["dispatched"]
            self._target_point_id = self._flight_plan.legs[0].to_point_id
            await self._sync_to_fleet()

            # DeliveryWorkflow runs its own compensation + finalize path on
            # failure and signals us back to IDLE, so we just need to wait out
            # the child — any ChildWorkflowError means the compensation ran and
            # there is nothing else to clean up here.
            with contextlib.suppress(ChildWorkflowError):
                await workflow.execute_child_workflow(
                    DeliveryWorkflow.run,
                    args=[
                        drone_id,
                        workflow.info().workflow_id,
                        fleet_workflow_id,
                        home_base_id,
                        order,
                        self._battery_pct,
                        model_name,
                    ],
                    id=self._current_delivery_workflow_id,
                    task_queue=TASK_QUEUE,
                )

            # Reset for next order. DeliveryWorkflow has already signaled the
            # final IDLE/battery state; these assignments keep in-process
            # fields coherent for the next loop iteration.
            self._current_order = None
            self._current_delivery_workflow_id = None
            self._flight_plan = None
            self._state = WorkflowState.IDLE
            self._battery_pct = 100.0
            self._signals = []
            self._target_point_id = None
            if self._home_location is not None:
                self._position = self._home_location.model_copy()
            await self._sync_to_fleet()

    @workflow.signal
    def assign_order(self, order: Order) -> None:
        self._pending_order = order

    @workflow.signal
    async def update_runtime(self, update: dict[str, Any]) -> None:
        """Merge a partial runtime update coming from an activity."""
        if "state" in update:
            self._state = WorkflowState(update["state"])
        if "position" in update and update["position"] is not None:
            self._position = Coordinate.model_validate(update["position"])
        if "battery_pct" in update:
            self._battery_pct = float(update["battery_pct"])
        if "target_point_id" in update:
            self._target_point_id = update["target_point_id"]
        if update.get("clear_signals"):
            self._signals = []
        if update.get("add_signal"):
            sig = update["add_signal"]
            if sig not in self._signals:
                self._signals = [*self._signals, sig]
        await self._sync_to_fleet()

    @workflow.signal
    async def advance_leg(self) -> None:
        plan = self._flight_plan
        if plan is None:
            return
        if plan.current_leg_index >= len(plan.legs):
            return
        plan.legs[plan.current_leg_index].status = FlightLegStatus.DONE
        plan.current_leg_index += 1
        if plan.current_leg_index < len(plan.legs):
            plan.legs[plan.current_leg_index].status = FlightLegStatus.ACTIVE
            self._target_point_id = plan.legs[plan.current_leg_index].to_point_id
        await self._sync_to_fleet()

    @workflow.signal
    async def low_battery(self) -> None:
        """Insert a visible DIVERT_TO_BASE leg into the current plan.

        The actual execution of the divert is handled by `DeliveryWorkflow`'s
        compensation saga — this signal's job is only to surface the reroute
        in the UI so the plan and the drone's state stay aligned.
        """
        plan = self._flight_plan
        if plan is None or self._home_base_id is None:
            return
        # Only worth inserting if there's still a future leg beyond the current one.
        if plan.current_leg_index + 1 >= len(plan.legs):
            return

        current_leg = plan.legs[plan.current_leg_index]
        divert = FlightLeg(
            kind=FlightLegKind.DIVERT_TO_BASE,
            from_point_id=current_leg.to_point_id,
            to_point_id=self._home_base_id,
            status=FlightLegStatus.PENDING,
        )
        plan.legs.insert(plan.current_leg_index + 1, divert)
        await self._sync_to_fleet()

    @workflow.signal
    def shutdown(self) -> None:
        self._shutdown = True

    @workflow.query
    def get_drone_state(self) -> DroneRuntimeState:
        return self._snapshot()

    def _snapshot(self) -> DroneRuntimeState:
        assert self._drone_id is not None
        assert self._name is not None
        assert self._home_base_id is not None
        assert self._position is not None
        return DroneRuntimeState(
            id=self._drone_id,
            name=self._name,
            home_base_id=self._home_base_id,
            state=self._state,
            position=self._position,
            battery_pct=self._battery_pct,
            workflow_id=self._current_delivery_workflow_id,
            current_order_id=self._current_order.id if self._current_order else None,
            signals=list(self._signals),
            target_point_id=self._target_point_id,
            flight_plan=self._flight_plan,
        )

    async def _sync_to_fleet(self) -> None:
        if self._fleet_workflow_id is None:
            return
        snapshot = self._snapshot()
        payload: dict[str, Any] = {
            "drone_id": snapshot.id,
            "name": snapshot.name,
            "home_base_id": snapshot.home_base_id,
            "state": snapshot.state.value,
            "position": snapshot.position.model_dump(),
            "battery_pct": snapshot.battery_pct,
            "workflow_id": snapshot.workflow_id,
            "current_order_id": snapshot.current_order_id,
            "signals": list(snapshot.signals),
            "target_point_id": snapshot.target_point_id,
            "flight_plan": snapshot.flight_plan.model_dump() if snapshot.flight_plan else None,
        }
        fleet_handle = workflow.get_external_workflow_handle(self._fleet_workflow_id)
        await fleet_handle.signal("update_drone", payload)
