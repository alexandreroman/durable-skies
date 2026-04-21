"""Pilot agent that controls a single drone.

The agent runs inside a Temporal Workflow through `GoogleAdkPlugin`, so every
LLM call and every tool invocation becomes a durable Temporal Activity. If the
worker crashes mid-delivery, Temporal replays the workflow and the agent
resumes at the exact step where it left off — without losing context.
"""

from datetime import timedelta

from google.adk.agents import Agent
from temporalio.common import RetryPolicy
from temporalio.contrib.google_adk_agents import TemporalModel
from temporalio.contrib.google_adk_agents.workflow import activity_tool

from ..activities import (
    dropoff_package,
    land_drone,
    navigate_drone,
    pickup_package,
    takeoff_drone,
)
from ..models import Order

DRONE_INSTRUCTIONS_TEMPLATE = """You are the autopilot of delivery drone {drone_id}.

Mission for order {order_id}:
1. takeoff_drone(drone_id="{drone_id}", drone_workflow_id="{drone_workflow_id}", \
fleet_workflow_id="{fleet_workflow_id}")
2. navigate_drone(drone_id="{drone_id}", from_point_id="{home_base_id}", \
to_point_id="{pickup_base_id}", drone_workflow_id="{drone_workflow_id}", \
fleet_workflow_id="{fleet_workflow_id}", kind="to_target")
3. pickup_package(drone_id="{drone_id}", order_id="{order_id}", \
base_id="{pickup_base_id}", drone_workflow_id="{drone_workflow_id}", \
fleet_workflow_id="{fleet_workflow_id}")
4. navigate_drone(drone_id="{drone_id}", from_point_id="{pickup_base_id}", \
to_point_id="{dropoff_point_id}", drone_workflow_id="{drone_workflow_id}", \
fleet_workflow_id="{fleet_workflow_id}", kind="to_target")
5. dropoff_package(drone_id="{drone_id}", order_id="{order_id}", \
dropoff_point_id="{dropoff_point_id}", drone_workflow_id="{drone_workflow_id}", \
fleet_workflow_id="{fleet_workflow_id}")
6. navigate_drone(drone_id="{drone_id}", from_point_id="{dropoff_point_id}", \
to_point_id="{home_base_id}", drone_workflow_id="{drone_workflow_id}", \
fleet_workflow_id="{fleet_workflow_id}", kind="returning")
7. land_drone(drone_id="{drone_id}", drone_workflow_id="{drone_workflow_id}", \
fleet_workflow_id="{fleet_workflow_id}")

Always pass the drone_id, drone_workflow_id, and fleet_workflow_id exactly as shown above.
If a tool raises battery_critical, stop calling tools and report the failure —
the workflow will run its compensation saga automatically.
Report clearly on each step.
"""


def build_drone_agent(
    drone_id: str,
    drone_workflow_id: str,
    fleet_workflow_id: str,
    order: Order,
    home_base_id: str,
    model_name: str,
) -> Agent:
    fast_retry = RetryPolicy(maximum_attempts=3)
    short = timedelta(seconds=30)
    long = timedelta(minutes=5)

    instruction = DRONE_INSTRUCTIONS_TEMPLATE.format(
        drone_id=drone_id,
        drone_workflow_id=drone_workflow_id,
        fleet_workflow_id=fleet_workflow_id,
        order_id=order.id,
        home_base_id=home_base_id,
        pickup_base_id=order.pickup_base_id,
        dropoff_point_id=order.dropoff_point_id,
    )

    return Agent(
        name=f"drone_pilot_{drone_id}",
        model=TemporalModel(model_name=model_name),
        description=f"Autopilot agent for drone {drone_id}.",
        instruction=instruction,
        tools=[
            activity_tool(takeoff_drone, start_to_close_timeout=short, retry_policy=fast_retry),
            activity_tool(land_drone, start_to_close_timeout=short, retry_policy=fast_retry),
            activity_tool(navigate_drone, start_to_close_timeout=long, retry_policy=fast_retry),
            activity_tool(pickup_package, start_to_close_timeout=short, retry_policy=fast_retry),
            activity_tool(dropoff_package, start_to_close_timeout=short, retry_policy=fast_retry),
        ],
    )
