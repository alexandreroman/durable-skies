---
name: "Redis telemetry split — raw telemetry leaves Temporal"
description: "Why drone position/battery live in Redis instead of being pushed as Temporal signals, and which business state still stays in Temporal"
type: project
---

# Redis telemetry split — raw telemetry leaves Temporal

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

**Why:** position/battery update every ~2 s per
in-flight drone. Pushing each via `update_runtime`
signal to DroneWorkflow was the single biggest
contributor to event history growth on the
long-lived entity workflows. Redis costs nothing
in Temporal events, and a lost telemetry reading
is recoverable (next nav step overwrites within
2 s) — unlike losing an order assignment or a
state transition, which are business-critical.

**How to apply:** the split between "business
state in Temporal" and "volatile telemetry in
Redis" is load-bearing for the demo's event
budget. Future edits must respect:

1. **Telemetry writes NEVER raise.** `write_drone_
   telemetry` swallows `RedisError` and `OSError`.
   An activity must never abort a mission because
   Redis flinched. If you add new telemetry fields,
   keep the same swallow contract.
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
   `None`; `/fleet` falls back to the workflow
   query snapshot (stale position/battery but
   correct business state). Missions keep running
   because writes swallow errors.
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
