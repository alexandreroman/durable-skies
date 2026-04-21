"""Helpers that let activities push state updates to a per-drone `DroneWorkflow`.

Activities are outside the workflow sandbox, so they connect to Temporal with
a plain `Client` and send signals. The client is shared with `fleet_signal` to
avoid reconnecting on every activity invocation.
"""

from __future__ import annotations

from typing import Any

from ..models import Coordinate, WorkflowState
from .fleet_signal import get_client


async def update_drone(
    drone_workflow_id: str,
    *,
    state: WorkflowState | None = None,
    position: Coordinate | None = None,
    battery_pct: float | None = None,
    target_point_id: str | None = None,
    add_signal: str | None = None,
    clear_signals: bool = False,
) -> None:
    """Signal the per-drone entity workflow with a partial runtime update.

    Only the fields set on the payload are merged on the workflow side — missing
    fields leave the current value untouched.
    """
    payload: dict[str, Any] = {}
    if state is not None:
        payload["state"] = state.value
    if position is not None:
        payload["position"] = position.model_dump()
    if battery_pct is not None:
        payload["battery_pct"] = battery_pct
    if target_point_id is not None:
        payload["target_point_id"] = target_point_id
    if add_signal is not None:
        payload["add_signal"] = add_signal
    if clear_signals:
        payload["clear_signals"] = True

    client = await get_client()
    handle = client.get_workflow_handle(drone_workflow_id)
    await handle.signal("update_runtime", payload)


async def advance_leg(drone_workflow_id: str) -> None:
    """Tell the per-drone entity workflow that the current flight leg is complete."""
    client = await get_client()
    handle = client.get_workflow_handle(drone_workflow_id)
    await handle.signal("advance_leg")
