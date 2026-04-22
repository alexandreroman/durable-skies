"""Shared helpers used by multiple workflow modules.

Kept deliberately tiny: workflow code must stay deterministic, so anything that
lands here must either be pure Python or go through `workflow.*` primitives.
"""

from datetime import timedelta

from temporalio import workflow

from ..activities import log_fleet_event
from ..models import FleetEvent, FleetEventType

_LOG_EVENT_TIMEOUT = timedelta(seconds=5)


async def log_event(message: str, event_type: FleetEventType) -> None:
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
