"""durable-skies: durable multi-agent drone delivery demo."""

__version__ = "0.1.0"

TASK_QUEUE = "durable-skies"


def drone_workflow_id(drone_id: str) -> str:
    """Canonical workflow id for a per-drone long-lived entity workflow."""
    return f"drone-{drone_id.lower()}"
