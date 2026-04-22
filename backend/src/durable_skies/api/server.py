"""HTTP gateway between the Nuxt UI and the Temporal fleet.

- `POST /orders` submits a new order (Temporal signal on the running fleet).
- `GET  /fleet` snapshots the fleet state via a Temporal query.
- `GET  /health` static health check.

On startup the API auto-starts the singleton `FleetWorkflow` (id
`fleet-supervisor`) so the UI has something to poll immediately.
"""

import asyncio
import contextlib
import logging
from contextlib import asynccontextmanager
from typing import ClassVar

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from temporalio.client import Client, WorkflowFailureError, WorkflowQueryFailedError
from temporalio.contrib.google_adk_agents import GoogleAdkPlugin
from temporalio.exceptions import WorkflowAlreadyStartedError
from temporalio.service import RPCError

from .. import MIN_DISPATCH_BATTERY_PCT, TASK_QUEUE, drone_workflow_id, order_workflow_id
from ..config import get_settings
from ..events import read_fleet_events
from ..models import Coordinate, DroneRuntimeState, FleetState, Order, WorkflowState
from ..redis_client import close_redis_client
from ..telemetry import read_drone_telemetries
from ..workflows import DroneWorkflow, FleetWorkflow, OrderWorkflow
from ..world import initial_drone_startups, initial_drones

# Baseline fleet definitions are constant at runtime; compute once so the 500 ms
# /fleet polling loop doesn't rebuild Pydantic models on every tick. Consumers
# must treat these as read-only — `_overlay_telemetry` already uses model_copy.
_BASELINE_DRONES: list[DroneRuntimeState] = initial_drones()
_BASELINE_DRONES_BY_ID: dict[str, DroneRuntimeState] = {d.id: d for d in _BASELINE_DRONES}
_BASELINE_DRONE_STARTUPS: list[tuple[str, str, str, Coordinate]] = initial_drone_startups()

FLEET_WORKFLOW_ID = "fleet-supervisor"

log = logging.getLogger("durable_skies.api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    client = await Client.connect(
        settings.temporal_address,
        namespace=settings.temporal_namespace,
        plugins=[GoogleAdkPlugin()],
    )
    app.state.client = client

    # Ensure the fleet supervisor is running. If it was already started, that's fine.
    try:
        await client.start_workflow(
            FleetWorkflow.run,
            args=[settings.anthropic_model, None, settings.anthropic_fast_model],
            id=FLEET_WORKFLOW_ID,
            task_queue=TASK_QUEUE,
        )
        log.info("Started FleetWorkflow %s", FLEET_WORKFLOW_ID)
    except WorkflowAlreadyStartedError:
        log.info("FleetWorkflow %s already running", FLEET_WORKFLOW_ID)

    # Start one DroneWorkflow per drone. These are long-lived entity workflows
    # that own per-drone runtime state and route orders to DeliveryWorkflow children.
    for drone_id, name, home_base_id, home_location in _BASELINE_DRONE_STARTUPS:
        wf_id = drone_workflow_id(drone_id)
        try:
            await client.start_workflow(
                DroneWorkflow.run,
                args=[
                    drone_id,
                    name,
                    home_base_id,
                    home_location,
                    settings.anthropic_model,
                ],
                id=wf_id,
                task_queue=TASK_QUEUE,
            )
            log.info("Started DroneWorkflow %s", wf_id)
        except WorkflowAlreadyStartedError:
            log.info("DroneWorkflow %s already running", wf_id)

    try:
        yield
    finally:
        await close_redis_client()


app = FastAPI(title="durable-skies", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


async def _query_drone(client: Client, drone_id: str) -> DroneRuntimeState | None:
    """Query a single DroneWorkflow for its live runtime state.

    Silently downgrades any per-drone query failure — timeout, RPC failure
    (worker unreachable, task in failed state), or query-handler exception
    (e.g. replay non-determinism) — to None so one unresponsive drone doesn't
    take down the whole /fleet response. The caller falls back to the baseline
    snapshot for that drone.
    """
    handle = client.get_workflow_handle(drone_workflow_id(drone_id))
    try:
        return await asyncio.wait_for(handle.query(DroneWorkflow.get_drone_state), timeout=2.0)
    except (TimeoutError, WorkflowFailureError, WorkflowQueryFailedError, RPCError):
        return None


def _overlay_telemetry(drone: DroneRuntimeState, telemetry: dict | None) -> DroneRuntimeState:
    """Merge Redis telemetry on top of a workflow-backed drone snapshot.

    Position, battery, and target_point_id come from Redis (fresh, per-step);
    state, signals, flight_plan, and current_order_id stay from the workflow
    query (authoritative for business state).
    """
    if telemetry is None:
        return drone
    update: dict[str, object] = {}
    if (pos := telemetry.get("position")) is not None:
        update["position"] = Coordinate.model_validate(pos)
    if (battery := telemetry.get("battery_pct")) is not None:
        update["battery_pct"] = float(battery)
    if "target_point_id" in telemetry:
        update["target_point_id"] = telemetry["target_point_id"]
    return drone.model_copy(update=update) if update else drone


@app.get("/fleet", response_model=FleetState)
async def get_fleet() -> FleetState:
    client: Client = app.state.client
    fleet_handle = client.get_workflow_handle(FLEET_WORKFLOW_ID)

    # Queries need a live worker; cap the wait so a worker restart doesn't freeze the UI poll loop.
    # The fleet query is authoritative for bases/pending_orders_count and the dispatching flag;
    # per-drone queries provide business state (state enum, signals, flight_plan, current_order_id);
    # Redis telemetry provides live position/battery on top; the fleet event log comes from Redis.
    # Fire everything in parallel.
    drone_ids = list(_BASELINE_DRONES_BY_ID.keys())
    fleet_task = asyncio.create_task(asyncio.wait_for(fleet_handle.query(FleetWorkflow.get_fleet_state), timeout=2.0))
    drone_tasks: dict[str, asyncio.Task[DroneRuntimeState | None]] = {
        drone_id: asyncio.create_task(_query_drone(client, drone_id)) for drone_id in drone_ids
    }
    telemetry_task = asyncio.create_task(read_drone_telemetries(drone_ids))
    events_task = asyncio.create_task(read_fleet_events())

    try:
        fleet_state = await fleet_task
    except TimeoutError as err:
        for task in drone_tasks.values():
            task.cancel()
        telemetry_task.cancel()
        events_task.cancel()
        log.warning("Fleet query timed out; worker may be unavailable")
        raise HTTPException(status_code=503, detail="fleet query timed out — worker may be unavailable") from err
    except WorkflowFailureError as err:  # workflow failed: surface as 503
        for task in drone_tasks.values():
            task.cancel()
        telemetry_task.cancel()
        events_task.cancel()
        raise HTTPException(status_code=503, detail=str(err)) from err

    await asyncio.gather(*drone_tasks.values(), telemetry_task, events_task)
    telemetries = telemetry_task.result()

    merged: list[DroneRuntimeState] = []
    for drone_id in drone_ids:
        base = _BASELINE_DRONES_BY_ID[drone_id]
        queried = drone_tasks[drone_id].result() or base
        merged.append(_overlay_telemetry(queried, telemetries.get(drone_id)))

    dispatchable = sum(
        1 for d in merged if d.state == WorkflowState.IDLE and d.battery_pct > MIN_DISPATCH_BATTERY_PCT and not d.paused
    )
    return fleet_state.model_copy(
        update={
            "drones": merged,
            "events": events_task.result(),
            "dispatchable_drones_count": dispatchable,
        }
    )


@app.post("/orders")
async def submit_order(order: Order) -> dict[str, str]:
    client: Client = app.state.client
    wf_id = order_workflow_id(order.id)
    # Re-POSTing the same order id is a no-op.
    with contextlib.suppress(WorkflowAlreadyStartedError):
        await client.start_workflow(
            OrderWorkflow.run,
            args=[order, FLEET_WORKFLOW_ID],
            id=wf_id,
            task_queue=TASK_QUEUE,
        )
    return {"workflow_id": wf_id, "order_id": order.id}


def _assert_known_drone(drone_id: str) -> None:
    if drone_id not in _BASELINE_DRONES_BY_ID:
        raise HTTPException(status_code=404, detail=f"unknown drone id: {drone_id}")


@app.post("/drones/{drone_id}/pause")
async def pause_drone(drone_id: str) -> dict[str, bool]:
    _assert_known_drone(drone_id)
    client: Client = app.state.client
    handle = client.get_workflow_handle(drone_workflow_id(drone_id))
    await handle.signal("pause_drone")
    return {"ok": True}


@app.post("/drones/{drone_id}/resume")
async def resume_drone(drone_id: str) -> dict[str, bool]:
    _assert_known_drone(drone_id)
    client: Client = app.state.client
    handle = client.get_workflow_handle(drone_workflow_id(drone_id))
    await handle.signal("resume_drone")
    return {"ok": True}


class _QuietPollingAccessFilter(logging.Filter):
    _QUIET: ClassVar[set[tuple[str, str]]] = {("GET", "/fleet"), ("GET", "/health")}

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if not isinstance(args, tuple) or len(args) < 5:
            return True
        _client, method, full_path, _http_version, status = args
        if not isinstance(full_path, str):
            return True
        path = full_path.split("?", 1)[0]
        if (method, path) not in self._QUIET:
            return True
        try:
            code = int(status)
        except (TypeError, ValueError):
            return True
        return not 200 <= code < 400


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    logging.getLogger("uvicorn.access").addFilter(_QuietPollingAccessFilter())
    settings = get_settings()
    uvicorn.run(
        "durable_skies.api.server:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=False,
    )


if __name__ == "__main__":
    main()
