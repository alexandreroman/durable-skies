"""Temporal worker entry point.

Runs workflows (fleet supervisor + per-delivery) and activities (drone control
+ delivery) against the configured Temporal service. The `GoogleAdkPlugin`
handles ADK-specific wiring: Pydantic payload converter, sandbox passthrough
for ADK / Gemini / MCP modules, and deterministic replacements for time and
UUID primitives inside workflow code.
"""

import asyncio
import logging

from temporalio.client import Client
from temporalio.contrib.google_adk_agents import GoogleAdkPlugin
from temporalio.worker import Worker
from temporalio.worker.workflow_sandbox import SandboxedWorkflowRunner, SandboxRestrictions

from . import TASK_QUEUE
from .activities import all_activities
from .config import get_settings
from .workflows import all_workflows

log = logging.getLogger("durable_skies.worker")

# pydantic v2 imports its compiled core (`pydantic_core`, `pydantic_core._pydantic_core`,
# `pydantic_core.core_schema`) lazily on first validation. That first call happens
# *inside* a workflow task, after the sandbox has snapshotted its module table, which
# triggers "imported after initial workflow load" warnings. Marking the package as
# passthrough lets the sandbox import it freely without tracking — safe because it's
# a pure C/Python extension with no nondeterminism risk. The `GoogleAdkPlugin`'s
# `workflow_runner` hook will layer its own passthrough modules (google.adk, google.genai,
# mcp) on top of this runner, so both sets are preserved.
_workflow_runner = SandboxedWorkflowRunner(
    restrictions=SandboxRestrictions.default.with_passthrough_modules("pydantic_core"),
)


async def run() -> None:
    settings = get_settings()

    client = await Client.connect(
        settings.temporal_address,
        namespace=settings.temporal_namespace,
        plugins=[GoogleAdkPlugin()],
    )

    worker = Worker(
        client,
        task_queue=TASK_QUEUE,
        workflows=all_workflows,
        activities=all_activities,
        workflow_runner=_workflow_runner,
    )

    log.info("Worker starting on task queue %s", TASK_QUEUE)
    await worker.run()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    asyncio.run(run())


if __name__ == "__main__":
    main()
