---
name: "Redis split — raw telemetry + event log leave Temporal"
description: "Why drone position/battery and the fleet event log live in Redis instead of being pushed as Temporal signals, and which business state still stays in Temporal"
type: project
---

# Redis split — raw telemetry + event log leave Temporal

Two high-frequency observability streams now live
in Redis instead of Temporal history:

## Drone telemetry

Drone position, battery, and target_point_id are
written to Redis by the `navigate_drone` activity
at every nav step. The FastAPI gateway merges the
latest Redis entry into `GET /fleet` by overlaying
it on top of the DroneWorkflow query snapshot.

- Redis key: `drone:{drone_id}:telemetry`
- Value: JSON blob `{position, battery_pct,
  target_point_id, state}`
- TTL: 10 s (> nav-step cadence of 2 s)
- Shared module: `backend/src/durable_skies/
  telemetry.py` (used by both activity writers
  and the API reader)

## Fleet event log

The human-readable event log (takeoff, pickup,
delivered, dispatcher decisions, etc.) is written
to a Redis list by activities. The API reads the
list and merges it into `GET /fleet`.

- Redis key: `fleet:events` (Redis list)
- Value per entry: JSON-serialized `FleetEvent`
  `{id, time, type, message}`
- Capped via `LPUSH + LTRIM 0 199` → last 200
  entries (no TTL on the list itself)
- Shared module: `backend/src/durable_skies/
  events.py`
- Activity: `log_fleet_event` in
  `activities/fleet.py` — invoked from workflow
  code as a **local activity** (1 marker event
  vs 3 for a regular activity) to keep the event
  overhead minimal when the caller is a workflow.
- Activities call `write_fleet_event` directly
  (non-deterministic context, no wrapper needed).

## Drone availability registry

The dispatcher's drone registry is also in Redis
now — the FleetWorkflow no longer holds
`self._drones`. Each DroneWorkflow publishes its
availability on every state-enum transition; the
dispatcher reads the aggregate snapshot at
dispatch time via a local activity.

- Redis key: `fleet:availability` (Redis Hash,
  one field per drone, keyed by drone id)
- Value per entry: JSON-serialized
  `DroneAvailability` `{drone_id, name,
  home_base_id, state, battery_pct,
  current_order_id, updated_at}`
- Shared module: `backend/src/durable_skies/
  availability.py`
- Activities in `activities/fleet.py`:
  - `write_drone_availability_activity` —
    DroneWorkflow publishes via local activity
    on every state-enum transition.
  - `read_drone_availabilities_activity` —
    FleetWorkflow reads via local activity at
    dispatch time.
- **No staleness filter on read.** The reader
  returns the full hash (only corrupt entries
  are skipped). See
  `staleness_filter_antipattern.md` for why the
  original 60 s filter was removed — it conflicts
  fundamentally with the "write only on enum
  transition" invariant and left steady-state
  IDLE drones invisible to the dispatcher.

**Why:** position/battery update every ~2 s per
in-flight drone. Pushing each via `update_runtime`
signal to DroneWorkflow was the single biggest
contributor to event history growth on the
long-lived entity workflows. The event log added
~16 extra `append_event` signals to FleetWorkflow
per delivery for pure UI observability. Redis
costs nothing in Temporal events, and a lost
telemetry reading or event-log line is recoverable
(next nav step overwrites within 2 s; UI events
are observability-only) — unlike losing an order
assignment or a state transition, which are
business-critical.

**How to apply:** the split between "business
state in Temporal" and "volatile telemetry in
Redis" is load-bearing for the demo's event
budget. Future edits must respect:

1. **All Redis writes NEVER raise.**
   `write_drone_telemetry`, `write_fleet_event`,
   and `write_drone_availability` all swallow
   `RedisError` and `OSError`. An activity must
   never abort a mission because Redis flinched.
   If you add new telemetry fields, new event-log
   callsites, or new availability fields, keep
   the same swallow contract.
2. **Workflow determinism.** `redis.asyncio` is
   imported transitively through `telemetry.py` →
   `activities/drone.py` → `workflows/delivery.py`.
   The sandbox tolerates the import, but workflows
   must NEVER call telemetry functions directly.
   Redis I/O happens only in activities and the API.
3. **DeliveryWorkflow owns the RETURNING
   transition.** Since `navigate_drone` no longer
   sets state per step, DeliveryWorkflow signals
   `update_runtime({"state": "RETURNING"})` to the
   drone handle after `dropoff_package` and before
   the returning nav leg. Removing this resurrects
   the "drone stays DELIVERING on the way home"
   bug.
4. **Incident path still uses a Temporal signal.**
   When `battery_critical` fires, the activity
   signals `update_drone(state=INCIDENT,
   add_signal="battery_critical")` AND writes one
   final telemetry entry with `state=INCIDENT`.
   The signal is required — it triggers
   `_sync_to_fleet` so the dispatcher agent sees
   the drone is out.
5. **Graceful Redis degradation.** If Redis is
   down, `read_drone_telemetries` returns all
   `None` and `read_fleet_events` returns `[]`;
   `/fleet` falls back to the workflow query
   snapshot (stale position/battery but correct
   business state; empty event log). Missions
   keep running because writes swallow errors.
6. **API overlay order:** workflow query is
   authoritative for `state`, `signals`,
   `flight_plan`, `current_order_id`. Redis is
   authoritative for `position`, `battery_pct`,
   `target_point_id`. Do NOT let Redis override
   the former — it only carries a snapshot of
   state for observability, not the ground truth.

## Relationship to the earlier fleet push/pull split

This supersedes the "fleet pulls position/battery/
flight_plan via a 6-fanout Temporal query" design
for position and battery specifically. `flight_
plan`, `state`, `signals`, `current_order_id` are
still pulled via Temporal queries. See
`fleet_push_pull_split.md` for the invariants that
still apply to the query-based pull path.
