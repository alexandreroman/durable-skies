"""Per-order workflow.

One long-lived workflow per submitted order. Acts as a durable per-order state
machine: forwards the order to the fleet queue, waits for the DeliveryWorkflow
to report the outcome via `delivery_done`, and exits. Makes every order
individually queryable and cancellable in the Temporal UI without duplicating
the queue that `FleetWorkflow` already owns.
"""

from temporalio import workflow

from ..models import Order, OrderStatus


@workflow.defn
class OrderWorkflow:
    def __init__(self) -> None:
        self._status: OrderStatus = OrderStatus.PENDING
        self._success: bool | None = None
        self._message: str | None = None

    @workflow.run
    async def run(self, order: Order, fleet_workflow_id: str) -> dict:
        fleet_handle = workflow.get_external_workflow_handle(fleet_workflow_id)
        await fleet_handle.signal("submit_order", order)

        await workflow.wait_condition(lambda: self._success is not None)

        self._status = OrderStatus.DELIVERED if self._success else OrderStatus.FAILED
        return {
            "order_id": order.id,
            "success": bool(self._success),
            "message": self._message or "",
        }

    @workflow.signal
    def mark_assigned(self) -> None:
        if self._status == OrderStatus.PENDING:
            self._status = OrderStatus.ASSIGNED

    @workflow.signal
    def mark_in_progress(self) -> None:
        if self._status in (OrderStatus.PENDING, OrderStatus.ASSIGNED):
            self._status = OrderStatus.IN_PROGRESS

    @workflow.signal
    def delivery_done(self, success: bool, message: str) -> None:
        self._success = success
        self._message = message

    @workflow.query
    def get_state(self) -> dict:
        return {
            "status": self._status.value,
            "success": self._success,
            "message": self._message,
        }
