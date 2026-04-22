"""Anomaly handler agent: picks a recovery action after an in-flight incident.

The agent is invoked from `DeliveryWorkflow` when an activity in the mission
loop raises. It writes its decision to session state via `submit_recovery` so
the workflow branches deterministically on a validated action string.
"""

from google.adk.agents import Agent
from google.adk.tools import ToolContext
from temporalio.contrib.google_adk_agents import TemporalModel
from temporalio.workflow import ActivityConfig

RECOVERY_DECISION_KEY = "recovery_decision"

ACTION_ABORT = "abort_return_home"
ACTION_EMERGENCY_LAND = "emergency_land_nearest_base"
ACTION_DIVERT_RECHARGE = "divert_to_recharge"

_VALID_ACTIONS = frozenset({ACTION_ABORT, ACTION_EMERGENCY_LAND, ACTION_DIVERT_RECHARGE})

_ANOMALY_INSTRUCTION = """You are the flight-safety officer for a delivery drone
that has raised an in-flight incident. Based on the incident details, choose ONE
recovery action by calling `submit_recovery(action, reasoning)`.

Valid actions:
- abort_return_home: fly straight back to the drone's home base, order failed.
- emergency_land_nearest_base: land at the nearest base which may not be home,
  order failed.
- divert_to_recharge: fly to the nearest base, recharge the battery, then return
  home — order still failed in this version.

Be concise in your reasoning (one sentence).
"""


def submit_recovery(action: str, reasoning: str, tool_context: ToolContext) -> dict[str, str]:
    """Record the recovery choice in session state, coercing invalid actions to ABORT."""
    safe_action = action if action in _VALID_ACTIONS else ACTION_ABORT
    tool_context.state[RECOVERY_DECISION_KEY] = {"action": safe_action, "reasoning": reasoning}
    return {"status": "ok", "action": safe_action}


def build_anomaly_agent(model_name: str) -> Agent:
    return Agent(
        name="anomaly_handler",
        model=TemporalModel(
            model_name=model_name,
            activity_config=ActivityConfig(summary="Anomaly handler · Recovery action"),
        ),
        description="Picks a recovery action after an in-flight drone incident.",
        instruction=_ANOMALY_INSTRUCTION,
        tools=[submit_recovery],
    )


__all__ = [
    "ACTION_ABORT",
    "ACTION_DIVERT_RECHARGE",
    "ACTION_EMERGENCY_LAND",
    "RECOVERY_DECISION_KEY",
    "build_anomaly_agent",
]
