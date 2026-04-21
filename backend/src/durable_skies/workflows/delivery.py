"""Delivery workflow.

One workflow per order. Spins up a per-drone ADK pilot agent and lets it drive
a full pickup → dropoff → return trip. The Google ADK plugin routes every LLM
call and tool call through Temporal Activities, so the whole trip is durable.

The workflow signals the per-drone entity (`DroneWorkflow`) at each phase
transition; the entity then forwards state to the fleet so the UI (which polls
the fleet) stays in sync.
"""

from datetime import timedelta

from google.adk.runners import InMemoryRunner
from google.genai import types
from temporalio import workflow
from temporalio.exceptions import ActivityError, ApplicationError

with workflow.unsafe.imports_passed_through():
    from ..agents.drone import build_drone_agent

from ..models import FleetEvent, FleetEventType, Order, WorkflowState
from ..world import DEPOTS


@workflow.defn
class DeliveryWorkflow:
    @workflow.run
    async def run(
        self,
        drone_id: str,
        drone_workflow_id: str,
        fleet_workflow_id: str,
        home_base_id: str,
        order: Order,
        model_name: str,
    ) -> str:
        drone_handle = workflow.get_external_workflow_handle(drone_workflow_id)
        fleet_handle = workflow.get_external_workflow_handle(fleet_workflow_id)

        agent = build_drone_agent(
            drone_id=drone_id,
            drone_workflow_id=drone_workflow_id,
            fleet_workflow_id=fleet_workflow_id,
            order=order,
            home_base_id=home_base_id,
            model_name=model_name,
        )
        runner = InMemoryRunner(agent=agent, app_name="durable-skies")
        session = await runner.session_service.create_session(
            app_name="durable-skies",
            user_id=drone_id,
        )

        prompt = f"Start delivery of order {order.id}."

        try:
            async for _ in runner.run_async(
                user_id=drone_id,
                session_id=session.id,
                new_message=types.Content(role="user", parts=[types.Part(text=prompt)]),
            ):
                pass
        except (ApplicationError, ActivityError) as err:
            await self._compensate(drone_handle, fleet_handle, drone_id, home_base_id)
            await self._finalize(drone_handle, fleet_handle, drone_id, home_base_id, incident=True)
            return f"Order {order.id} aborted: {err}"

        await self._finalize(drone_handle, fleet_handle, drone_id, home_base_id, incident=False)
        return f"Order {order.id} completed"

    async def _compensate(self, drone_handle, fleet_handle, drone_id: str, home_base_id: str) -> None:
        await fleet_handle.signal(
            "append_event",
            FleetEvent(
                id=workflow.uuid4().hex,
                time=workflow.now().isoformat(),
                type=FleetEventType.SIGNAL,
                message=f"↩️ {drone_id} return to base",
            ),
        )
        # Surface the reroute in the drone's visible flight plan.
        await drone_handle.signal("low_battery")
        await drone_handle.signal(
            "update_runtime",
            {
                "state": WorkflowState.RETURNING.value,
                "target_point_id": home_base_id,
                "add_signal": "incident",
            },
        )
        # Short settle before landing; real flight back would run via navigate_drone,
        # but the compensation path keeps it simple — teleport + land.
        await workflow.sleep(timedelta(seconds=2))

    async def _finalize(
        self,
        drone_handle,
        fleet_handle,
        drone_id: str,
        home_base_id: str,
        *,
        incident: bool,
    ) -> None:
        home_location = next(b.location for b in DEPOTS if b.id == home_base_id)

        await drone_handle.signal(
            "update_runtime",
            {
                "state": WorkflowState.COMPLETED.value,
                "position": home_location.model_dump(),
                "target_point_id": None,
            },
        )
        if not incident:
            await drone_handle.signal("update_runtime", {"add_signal": "delivered"})
        await fleet_handle.signal(
            "append_event",
            FleetEvent(
                id=workflow.uuid4().hex,
                time=workflow.now().isoformat(),
                type=FleetEventType.SUCCESS,
                message=f"🏠 {drone_id} home ✓",
            ),
        )

        # Mimic the prototype's "respawn": wait a beat, then flip IDLE with fresh battery.
        await workflow.sleep(timedelta(seconds=3))
        await drone_handle.signal(
            "update_runtime",
            {
                "state": WorkflowState.IDLE.value,
                "battery_pct": 100.0,
                "target_point_id": None,
                "clear_signals": True,
            },
        )
