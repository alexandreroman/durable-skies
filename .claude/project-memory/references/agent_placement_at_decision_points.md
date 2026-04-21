---
name: "Agents only at decision points, never to script deterministic sequences"
description: "Design rule: add ADK agents only where the LLM makes a real branching decision; fixed tool sequences stay as deterministic workflow code"
type: project
---

# Agents only at decision points, never to script deterministic sequences

ADK agents in this repo live at genuine branching
decisions where LLM reasoning adds value. Today:

- **Dispatcher** — picks the best idle drone for
  an incoming order. Composed as a
  `SequentialAgent[ParallelAgent[fleet_analyst,
  order_analyst], dispatcher_picker]`. Writes its
  choice to session state via `submit_dispatch`.
- **Anomaly handler** — on `battery_critical`,
  chooses one of `abort_return_home`,
  `emergency_land_nearest_base`,
  `divert_to_recharge`. Single `Agent` with a
  `submit_recovery` tool.

The per-drone pilot agent was removed because it
only sequenced 7 fixed tool calls (takeoff → nav
→ pickup → nav → dropoff → nav → land) with zero
real decisions. The mission now lives as a
deterministic `workflow.execute_activity` loop
inside `DeliveryWorkflow.run`.

**Why:** LLM calls cost latency, money, and
reliability. Paying those costs for behavior that
is actually fixed gives the demo nothing and
makes the Temporal×ADK story weaker, not
stronger — the valuable pattern is "durable
reasoning at decision points", not "LLM as tool
sequencer".

**How to apply:** when asked to add a new agent
(e.g. "mission planner", "customer comms",
"fleet strategist"), first check whether the
behavior has real branching that depends on
judgment over heterogeneous signals. If the
answer is a fixed sequence of activity calls,
keep it as workflow code. Reserve the agent
pattern for places where different inputs should
legitimately produce different tool-call
sequences.
