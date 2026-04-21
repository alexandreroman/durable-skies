"""Helpers that let activities push events back to `FleetWorkflow`.

Activities are outside the workflow sandbox, so they connect to Temporal with
a plain `Client` and send signals. The client is cached per worker process to
avoid reconnecting on every activity invocation.

Drone state updates go to the per-drone entity workflow — see `drone_signal.py`.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime

from temporalio.client import Client

from ..config import get_settings
from ..models import FleetEvent, FleetEventType

_client: Client | None = None
_client_lock = asyncio.Lock()


async def get_client() -> Client:
    global _client
    if _client is not None:
        return _client
    async with _client_lock:
        if _client is None:
            settings = get_settings()
            _client = await Client.connect(
                settings.temporal_address,
                namespace=settings.temporal_namespace,
            )
    return _client


async def append_event(
    fleet_workflow_id: str,
    message: str,
    event_type: FleetEventType = FleetEventType.INFO,
) -> None:
    event = FleetEvent(
        id=uuid.uuid4().hex,
        time=datetime.now(UTC).isoformat(),
        type=event_type,
        message=message,
    )
    client = await get_client()
    handle = client.get_workflow_handle(fleet_workflow_id)
    await handle.signal("append_event", event)
