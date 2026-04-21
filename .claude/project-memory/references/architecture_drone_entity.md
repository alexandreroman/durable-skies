---
name: "Per-drone entity workflow architecture"
description: "Backend uses one long-lived DroneWorkflow per physical drone; fleet is an aggregator only"
type: project
---

# Per-drone entity workflow architecture

The backend has three workflow types:

- **FleetWorkflow** (singleton, id `fleet-supervisor`): thin router, almost stateless. Only owns `pending_orders` + the dispatcher agent. Has **no drone registry of its own** — at dispatch time it calls `read_drone_availabilities` (a local activity) to read the `fleet:availability` Redis hash, picks a drone, and signals `assign_order` on its `DroneWorkflow`. The fleet event log and drone availability both live in Redis, not in workflow state. See `redis_telemetry_split.md` and `fleet_push_pull_split.md`.
- **DroneWorkflow** (one per drone, id `drone-<name-lowercased>`, e.g. `drone-alpha`): long-lived entity workflow that owns the drone's runtime state (position, battery, flight plan). Accepts orders via `assign_order` and runs each as a child `DeliveryWorkflow`. Activities signal it via `update_runtime` (partial state merge) and `advance_leg` (flight-plan progression). On every state-enum transition it publishes a fresh `DroneAvailability` snapshot to Redis via `write_drone_availability` (local activity) — this is the only path back to the dispatcher. The id helper lives in `durable_skies.__init__.drone_workflow_id(drone_id)` and lowercases the drone id.
- **DeliveryWorkflow** (one per order, id `delivery-<order_id>`): hosts the ADK pilot agent and drives the 7-step mission. Runs as a child of the owning `DroneWorkflow`. On failure, runs its own compensation + finalize saga by signaling the drone entity directly; the drone entity's next state transition propagates to Redis availability.

**Why:** The earlier design had `FleetWorkflow` both aggregating state and starting delivery children directly. Introducing `DroneWorkflow` entities lets each drone own its own durable state (including a visible `FlightPlan` that the UI renders), keeps fleet as a pure aggregator, and makes per-drone history/queries addressable by `drone-<name>` workflow id.

**How to apply:**

- Activities in `activities/drone.py` signal the drone entity (`update_runtime`, `advance_leg`) for state; they write event-log entries directly to Redis via `write_fleet_event` (no signal to the fleet).
- `DeliveryWorkflow` never signals the fleet for state — it always goes through the drone entity's `update_runtime`, and the drone entity publishes the resulting state transitions to Redis availability.
- New drone-level behavior (battery policies, per-drone queries, divert logic) belongs on `DroneWorkflow`, not on fleet.
- API startup (`api/server.py` `lifespan`) must start both the singleton fleet and one `DroneWorkflow` per entry in `world.initial_drones()`, swallowing `WorkflowAlreadyStartedError`. The drone list the API returns to the UI is built from `initial_drones()` + per-drone queries — the fleet no longer reports it.
- `DroneRuntimeState.flight_plan: FlightPlan | None` is the frontend contract for rendering the current plan.
