"""Per-drone entity workflow.

One long-lived workflow per physical drone. Owns the drone's runtime state
(position, battery, flight plan) and publishes its eligibility snapshot to the
Redis availability registry (`fleet:availability`) on every state-enum
transition. The singleton `FleetWorkflow` reads that registry at dispatch
time — it holds no drone registry of its own. Each incoming order is executed
as a child `DeliveryWorkflow`; the entity serializes orders — a new one is
accepted only after the current delivery has completed or failed.
"""

import contextlib
from datetime import timedelta
from typing import Any

from temporalio import workflow
from temporalio.exceptions import ChildWorkflowError

from .. import TASK_QUEUE
from ..activities import write_drone_availability_activity
from ..models import (
    Coordinate,
    DroneAvailability,
    DroneRuntimeState,
    FlightLeg,
    FlightLegKind,
    FlightLegStatus,
    FlightPlan,
    Order,
    WorkflowState,
)
from .delivery import DeliveryWorkflow

_HISTORY_THRESHOLD = 2000
_CHARGE_STEP_PCT = 2.0
_CHARGE_STEP_DELAY_S = 2.0
# Must match fleet._MIN_DISPATCH_BATTERY_PCT — see progressive_charging_and_dispatch_gate memory.
_MIN_DISPATCH_BATTERY_PCT = 40.0
_PUBLISH_TIMEOUT = timedelta(seconds=5)


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
        model_name: str,
        initial_battery_pct: float = 100.0,
    ) -> None:
        home_location = Coordinate.model_validate(home_location)
        self._drone_id = drone_id
        self._name = name
        self._home_base_id = home_base_id
        self._home_location = home_location
        self._position = home_location.model_copy()
        self._battery_pct = initial_battery_pct
        self._state = self._idle_state()

        # Publish an initial availability snapshot BEFORE the first wait_condition
        # so the dispatcher can see the drone exists from the first dispatch cycle.
        await self._publish_availability()

        while not self._shutdown:
            # Charge progressively while waiting for the next order. If an order arrives
            # or shutdown is signaled, bail out immediately.
            while self._pending_order is None and not self._shutdown and self._battery_pct < 100.0:
                await workflow.sleep(timedelta(seconds=_CHARGE_STEP_DELAY_S))
                if self._pending_order is not None or self._shutdown:
                    break
                prev_state = self._state
                self._battery_pct = min(100.0, self._battery_pct + _CHARGE_STEP_PCT)
                self._state = self._idle_state()
                # Only republish on state enum transitions (CHARGING -> IDLE at 40%);
                # battery ticks reach the UI via the API's telemetry pull path.
                if self._state != prev_state:
                    await self._publish_availability()

            # Battery is full (or we bailed out); wait for the order/shutdown or a
            # battery drop that should re-trigger charging (e.g. a test signal).
            await workflow.wait_condition(
                lambda: self._pending_order is not None or self._shutdown or self._battery_pct < 100.0
            )
            if self._battery_pct < 100.0 and self._pending_order is None and not self._shutdown:
                continue
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
            await self._publish_availability()

            # DeliveryWorkflow runs its own compensation saga; we only wait it out.
            with contextlib.suppress(ChildWorkflowError):
                await workflow.execute_child_workflow(
                    DeliveryWorkflow.run,
                    args=[
                        drone_id,
                        workflow.info().workflow_id,
                        home_base_id,
                        order,
                        self._battery_pct,
                        model_name,
                    ],
                    id=self._current_delivery_workflow_id,
                    task_queue=TASK_QUEUE,
                )

            self._current_order = None
            self._current_delivery_workflow_id = None
            self._flight_plan = None
            self._state = self._idle_state()
            self._signals = []
            self._target_point_id = None
            if self._home_location is not None:
                self._position = self._home_location.model_copy()
            await self._publish_availability()

            if workflow.info().get_current_history_length() > _HISTORY_THRESHOLD:
                workflow.continue_as_new(
                    args=[
                        drone_id,
                        name,
                        home_base_id,
                        home_location,
                        model_name,
                        self._battery_pct,
                    ],
                )

    @workflow.signal
    def assign_order(self, order: Order) -> None:
        self._pending_order = order

    @workflow.signal
    async def update_runtime(self, update: dict[str, Any]) -> None:
        """Merge a partial runtime update coming from an activity."""
        prev_state = self._state
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
        if self._state in (WorkflowState.IDLE, WorkflowState.CHARGING):
            self._state = self._idle_state()
        # Only publish when the state enum moves — dispatcher idle-detection depends on it.
        if self._state != prev_state:
            await self._publish_availability()

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
        # No availability publish: flight_plan changes don't affect dispatch eligibility.

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
        # No availability publish: flight_plan changes don't affect dispatch eligibility.

    @workflow.signal
    def shutdown(self) -> None:
        self._shutdown = True

    @workflow.query
    def get_drone_state(self) -> DroneRuntimeState:
        return self._snapshot()

    def _idle_state(self) -> WorkflowState:
        return WorkflowState.CHARGING if self._battery_pct <= _MIN_DISPATCH_BATTERY_PCT else WorkflowState.IDLE

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

    async def _publish_availability(self) -> None:
        """Upsert this drone's row in the Redis availability registry."""
        assert self._drone_id is not None
        assert self._name is not None
        assert self._home_base_id is not None
        availability = DroneAvailability(
            drone_id=self._drone_id,
            name=self._name,
            home_base_id=self._home_base_id,
            state=self._state,
            battery_pct=self._battery_pct,
            current_order_id=self._current_order.id if self._current_order else None,
            updated_at=workflow.now().isoformat(),
        )
        await workflow.execute_local_activity(
            write_drone_availability_activity,
            availability,
            start_to_close_timeout=_PUBLISH_TIMEOUT,
        )
