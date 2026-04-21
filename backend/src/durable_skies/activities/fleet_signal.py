"""Helpers that let activities push state and events back to `FleetWorkflow`.

Activities are outside the workflow sandbox, so they connect to Temporal with
a plain `Client` and send signals. The client is cached per worker process to
avoid reconnecting on every activity invocation.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
from typing import Any

from temporalio.client import Client

from ..config import get_settings
from ..models import Coordinate, FleetEvent, FleetEventType, WorkflowState

_client: Client | None = None
_client_lock = asyncio.Lock()


async def _get_client() -> Client:
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


async def update_drone(
    fleet_workflow_id: str,
    drone_id: str,
    *,
    state: WorkflowState | None = None,
    position: Coordinate | None = None,
    battery_pct: float | None = None,
    workflow_id: str | None = None,
    current_order_id: str | None = None,
    target_point_id: str | None = None,
    add_signal: str | None = None,
    clear_signals: bool = False,
) -> None:
    """Signal the fleet workflow with a partial drone update.

    Only the fields set on the payload are merged on the workflow side — missing
    fields leave the current value untouched.
    """
    payload: dict[str, Any] = {"drone_id": drone_id}
    if state is not None:
        payload["state"] = state.value
    if position is not None:
        payload["position"] = position.model_dump()
    if battery_pct is not None:
        payload["battery_pct"] = battery_pct
    if workflow_id is not None:
        payload["workflow_id"] = workflow_id
    if current_order_id is not None:
        payload["current_order_id"] = current_order_id
    if target_point_id is not None:
        payload["target_point_id"] = target_point_id
    if add_signal is not None:
        payload["add_signal"] = add_signal
    if clear_signals:
        payload["clear_signals"] = True

    client = await _get_client()
    handle = client.get_workflow_handle(fleet_workflow_id)
    await handle.signal("update_drone", payload)


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
    client = await _get_client()
    handle = client.get_workflow_handle(fleet_workflow_id)
    await handle.signal("append_event", event)
