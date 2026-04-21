"""HTTP gateway between the Nuxt UI and the Temporal fleet.

- `POST /orders` submits a new order (Temporal signal on the running fleet).
- `GET  /fleet` snapshots the fleet state via a Temporal query.
- `GET  /health` static health check.

On startup the API auto-starts the singleton `FleetWorkflow` (id
`fleet-supervisor`) so the UI has something to poll immediately.
"""

import logging
from contextlib import asynccontextmanager
from typing import ClassVar

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from temporalio.client import Client, WorkflowFailureError
from temporalio.contrib.google_adk_agents import GoogleAdkPlugin
from temporalio.exceptions import WorkflowAlreadyStartedError

from .. import TASK_QUEUE, drone_workflow_id, order_workflow_id
from ..config import get_settings
from ..models import FleetState, Order
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


@app.get("/fleet", response_model=FleetState)
async def get_fleet() -> FleetState:
    client: Client = app.state.client
    handle = client.get_workflow_handle(FLEET_WORKFLOW_ID)
    try:
        return await handle.query(FleetWorkflow.get_fleet_state)
    except WorkflowFailureError as err:  # workflow failed: surface as 503
        raise HTTPException(status_code=503, detail=str(err)) from err


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
