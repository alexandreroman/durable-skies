"""durable-skies: durable multi-agent drone delivery demo."""

__version__ = "0.1.0"

TASK_QUEUE = "durable-skies"

# Shared dispatch gate: a drone must be strictly above this battery level to be
# eligible for a new order. Also drives the IDLE/CHARGING split in DroneWorkflow.
MIN_DISPATCH_BATTERY_PCT = 40.0


def drone_workflow_id(drone_id: str) -> str:
    """Canonical workflow id for a per-drone long-lived entity workflow."""
    return f"drone-{drone_id.lower()}"


def order_workflow_id(order_id: str) -> str:
    """Canonical workflow id for a per-order OrderWorkflow."""
    return f"order-{order_id}"
