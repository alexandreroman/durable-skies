"""Dispatcher agent: picks the best idle drone for a new order.

Composed as a SequentialAgent that first runs two analysts in parallel
(fleet + order) and then calls the picker LLM. The picker emits its choice
through the `submit_dispatch` function tool which writes the decision into
session state so the workflow can read it back deterministically.
"""

from google.adk.agents import Agent, ParallelAgent, SequentialAgent
from google.adk.tools import ToolContext
from temporalio.contrib.google_adk_agents import TemporalModel

DISPATCH_DECISION_KEY = "dispatch_decision"

_FLEET_ANALYST_INSTRUCTION = """You are a fleet analyst.

The user message contains a JSON list of idle drones, each with: id, name,
home_base_id, battery_pct, position (lat/lon).

Briefly assess which drones are the best candidates for a new delivery based
on battery level and geographic position. Output a short paragraph — no
bullet lists, no JSON. Do not call any tools.
"""

_ORDER_ANALYST_INSTRUCTION = """You are an order analyst.

The user message contains a JSON Order with: id, pickup_base_id,
dropoff_point_id, payload_kg.

Briefly describe the delivery requirements (distance hints, payload weight,
any priority clues). Output a short paragraph — no bullet lists, no JSON.
Do not call any tools.
"""

_PICKER_INSTRUCTION = """You are the fleet dispatcher. Your job is to pick
ONE idle drone for the pending order by calling the tool
`submit_dispatch(drone_id, reasoning)`.

Fleet analysis:
{fleet_analysis}

Order analysis:
{order_analysis}

Balance battery level, proximity to the pickup base, and mission continuity.
Call `submit_dispatch` exactly once with the chosen drone id (must match one
of the idle drones) and a short reasoning (one sentence).
"""


def submit_dispatch(drone_id: str, reasoning: str, tool_context: ToolContext) -> dict[str, str]:
    """Record the dispatcher's choice in session state."""
    tool_context.state[DISPATCH_DECISION_KEY] = {"drone_id": drone_id, "reasoning": reasoning}
    return {"status": "ok"}


def build_dispatcher_agent(model_name: str) -> SequentialAgent:
    fleet_analyst = Agent(
        name="fleet_analyst",
        model=TemporalModel(model_name=model_name),
        description="Summarizes the pool of idle drones.",
        instruction=_FLEET_ANALYST_INSTRUCTION,
        output_key="fleet_analysis",
    )
    order_analyst = Agent(
        name="order_analyst",
        model=TemporalModel(model_name=model_name),
        description="Summarizes the pending order.",
        instruction=_ORDER_ANALYST_INSTRUCTION,
        output_key="order_analysis",
    )
    analysts = ParallelAgent(
        name="analysts",
        sub_agents=[fleet_analyst, order_analyst],
    )
    dispatcher_picker = Agent(
        name="dispatcher_picker",
        model=TemporalModel(model_name=model_name),
        description="Picks the drone that should handle the order.",
        instruction=_PICKER_INSTRUCTION,
        tools=[submit_dispatch],
    )
    return SequentialAgent(
        name="dispatcher",
        sub_agents=[analysts, dispatcher_picker],
    )


__all__ = ["DISPATCH_DECISION_KEY", "build_dispatcher_agent"]
