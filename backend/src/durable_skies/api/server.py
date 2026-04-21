"""HTTP gateway between the Nuxt UI and the Temporal fleet.

- `POST /orders` submits a new order (Temporal signal on the running fleet).
- `GET  /fleet` snapshots the fleet state via a Temporal query.
- `GET  /health` static health check.

On startup the API auto-starts the singleton `FleetWorkflow` (id
`fleet-supervisor`) so the UI has something to poll immediately.
"""

import logging
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from temporalio.client import Client, WorkflowFailureError
from temporalio.contrib.google_adk_agents import GoogleAdkPlugin
from temporalio.exceptions import WorkflowAlreadyStartedError

from .. import TASK_QUEUE
from ..config import get_settings
from ..models import FleetState, Order
from ..workflows import FleetWorkflow

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
    app.state.settings = settings

    # Ensure the fleet supervisor is running. If it was already started, that's fine.
    try:
        await client.start_workflow(
            FleetWorkflow.run,
            args=[settings.anthropic_model],
            id=FLEET_WORKFLOW_ID,
            task_queue=TASK_QUEUE,
        )
        log.info("Started FleetWorkflow %s", FLEET_WORKFLOW_ID)
    except WorkflowAlreadyStartedError:
        log.info("FleetWorkflow %s already running", FLEET_WORKFLOW_ID)

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
    handle = client.get_workflow_handle(FLEET_WORKFLOW_ID)
    await handle.signal("submit_order", order)
    return {"workflow_id": FLEET_WORKFLOW_ID, "order_id": order.id}


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    settings = get_settings()
    uvicorn.run(
        "durable_skies.api.server:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=False,
    )


if __name__ == "__main__":
    main()
