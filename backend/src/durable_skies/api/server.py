"""HTTP gateway between the Nuxt UI and the Temporal fleet.

- `POST /orders` submits a new order (Temporal signal on the running fleet).
- `GET  /fleet` snapshots the fleet state via a Temporal query.
- `GET  /health` static health check.

On startup the API auto-starts the singleton `FleetWorkflow` (id
`fleet-supervisor`) so the UI has something to poll immediately.
"""

import asyncio
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

from .. import TASK_QUEUE, drone_workflow_id, order_workflow_id
from ..config import get_settings
from ..models import DroneRuntimeState, FleetState, Order
from ..workflows import DroneWorkflow, FleetWorkflow, OrderWorkflow
from ..world import initial_drone_startups

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
            args=[settings.anthropic_model, None, None, None, 0, settings.anthropic_fast_model],
            id=FLEET_WORKFLOW_ID,
            task_queue=TASK_QUEUE,
        )
        log.info("Started FleetWorkflow %s", FLEET_WORKFLOW_ID)
    except WorkflowAlreadyStartedError:
        log.info("FleetWorkflow %s already running", FLEET_WORKFLOW_ID)

    # Start one DroneWorkflow per drone. These are long-lived entity workflows
    # that own per-drone runtime state and route orders to DeliveryWorkflow children.
    for drone_id, name, home_base_id, home_location in initial_drone_startups():
        wf_id = drone_workflow_id(drone_id)
        try:
            await client.start_workflow(
                DroneWorkflow.run,
                args=[
                    drone_id,
                    name,
                    home_base_id,
                    home_location,
                    FLEET_WORKFLOW_ID,
                    settings.anthropic_model,
                ],
                id=wf_id,
                task_queue=TASK_QUEUE,
            )
            log.info("Started DroneWorkflow %s", wf_id)
        except WorkflowAlreadyStartedError:
            log.info("DroneWorkflow %s already running", wf_id)

    yield


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
    take down the whole /fleet response. The caller falls back to fleet's
    cached snapshot for that drone.
    """
    handle = client.get_workflow_handle(drone_workflow_id(drone_id))
    try:
        return await asyncio.wait_for(handle.query(DroneWorkflow.get_drone_state), timeout=2.0)
    except (TimeoutError, WorkflowFailureError, WorkflowQueryFailedError, RPCError):
        return None


@app.get("/fleet", response_model=FleetState)
async def get_fleet() -> FleetState:
    client: Client = app.state.client
    fleet_handle = client.get_workflow_handle(FLEET_WORKFLOW_ID)

    # Queries need a live worker; cap the wait so a worker restart doesn't freeze the UI poll loop.
    # The fleet query is authoritative for events/bases/pending_orders_count; per-drone queries
    # provide fresh position/battery/flight_plan since drones no longer push nav-step updates.
    # Fire all queries up front so a slow fleet query doesn't serialize the drone fan-out.
    fleet_task = asyncio.create_task(
        asyncio.wait_for(fleet_handle.query(FleetWorkflow.get_fleet_state), timeout=2.0)
    )
    drone_tasks: dict[str, asyncio.Task[DroneRuntimeState | None]] = {
        drone_id: asyncio.create_task(_query_drone(client, drone_id))
        for drone_id, _name, _base_id, _loc in initial_drone_startups()
    }

    try:
        fleet_state = await fleet_task
    except TimeoutError as err:
        for task in drone_tasks.values():
            task.cancel()
        log.warning("Fleet query timed out; worker may be unavailable")
        raise HTTPException(status_code=503, detail="fleet query timed out — worker may be unavailable") from err
    except WorkflowFailureError as err:  # workflow failed: surface as 503
        for task in drone_tasks.values():
            task.cancel()
        raise HTTPException(status_code=503, detail=str(err)) from err

    await asyncio.gather(*drone_tasks.values())
    merged = [(drone_tasks[d.id].result() if d.id in drone_tasks else None) or d for d in fleet_state.drones]
    return fleet_state.model_copy(update={"drones": merged})


@app.post("/orders")
async def submit_order(order: Order) -> dict[str, str]:
    client: Client = app.state.client
    wf_id = order_workflow_id(order.id)
    try:
        await client.start_workflow(
            OrderWorkflow.run,
            args=[order, FLEET_WORKFLOW_ID],
            id=wf_id,
            task_queue=TASK_QUEUE,
        )
    except WorkflowAlreadyStartedError:
        # Re-POSTing the same order id is a no-op.
        pass
    return {"workflow_id": wf_id, "order_id": order.id}


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
