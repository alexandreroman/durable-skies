---
name: "Per-drone entity workflow architecture"
description: "Backend uses one long-lived DroneWorkflow per physical drone; fleet is an aggregator only"
type: project
---

# Per-drone entity workflow architecture

The backend has three workflow types:

- **FleetWorkflow** (singleton, id `fleet-supervisor`): thin aggregator. Owns the event log and the fleet snapshot for the UI. Routes incoming orders to an idle drone by signaling `assign_order` on its `DroneWorkflow`. Receives state updates from drones via an `update_drone` signal.
- **DroneWorkflow** (one per drone, id `drone-<name-lowercased>`, e.g. `drone-alpha`): long-lived entity workflow that owns the drone's runtime state (position, battery, flight plan). Accepts orders via `assign_order` and runs each as a child `DeliveryWorkflow`. Activities signal it via `update_runtime` (partial state merge) and `advance_leg` (flight-plan progression). It forwards every change to the fleet via `_sync_to_fleet`. The id helper lives in `durable_skies.__init__.drone_workflow_id(drone_id)` and lowercases the drone id.
- **DeliveryWorkflow** (one per order, id `delivery-<order_id>`): hosts the ADK pilot agent and drives the 7-step mission. Runs as a child of the owning `DroneWorkflow`. On failure, runs its own compensation + finalize saga by signaling the drone entity directly; the entity propagates to the fleet.

**Why:** The earlier design had `FleetWorkflow` both aggregating state and starting delivery children directly. Introducing `DroneWorkflow` entities lets each drone own its own durable state (including a visible `FlightPlan` that the UI renders), keeps fleet as a pure aggregator, and makes per-drone history/queries addressable by `drone-<name>` workflow id.

**How to apply:**

- Activities in `activities/drone.py` signal the drone entity (`update_runtime`, `advance_leg`) for state; they signal the fleet only for event-log entries (`append_event`).
- `DeliveryWorkflow` never signals the fleet for state — it always goes through the drone entity's `update_runtime`.
- New drone-level behavior (battery policies, per-drone queries, divert logic) belongs on `DroneWorkflow`, not on fleet.
- API startup (`api/server.py` `lifespan`) must start both the singleton fleet and one `DroneWorkflow` per entry in `world._DRONE_ASSIGNMENTS`, swallowing `WorkflowAlreadyStartedError`.
- `DroneRuntimeState.flight_plan: FlightPlan | None` is the frontend contract for rendering the current plan.
