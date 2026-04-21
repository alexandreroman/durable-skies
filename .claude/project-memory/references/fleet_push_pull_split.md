---
name: "Fleet push/pull split — transitions push, snapshots pull"
description: "Why DroneWorkflow only signals FleetWorkflow on state-enum transitions, and the API fans out queries for live position/battery/flight_plan at /fleet time"
type: project
---

# Fleet push/pull split — transitions push, snapshots pull

FleetWorkflow no longer receives every runtime
update from drones. The flow splits along the
kind of data:

- **Pushed** from DroneWorkflow to
  FleetWorkflow (via `_sync_to_fleet` →
  `update_drone` signal): only on **state-enum
  transitions** (IDLE → DISPATCHED → IN_FLIGHT →
  DELIVERING → RETURNING → IDLE, plus INCIDENT
  when it fires). Required so FleetWorkflow's
  dispatcher sees idle candidates without
  polling.
- **Pulled via Temporal query** by the API at
  `GET /fleet` time: `flight_plan`, `state`,
  `signals`, `current_order_id`,
  `target_point_id`. The API fires the fleet
  query and all per-drone queries in parallel
  (`asyncio.gather`, 2 s `asyncio.wait_for`
  each) and merges.
- **Pulled via Redis** at the same moment:
  `position` and `battery_pct` — see
  `redis_telemetry_split.md`. These fields used
  to be pulled via the DroneWorkflow query too,
  but were moved out of Temporal entirely
  because they refresh every ~2 s and dominated
  event growth.

**Why:** position/battery update every nav step
(~18 times per delivery per drone). Pushing
each via signal created the dominant event
volume on FleetWorkflow. Queries don't emit
history events, so pulling eliminates that cost
at the expense of a fanout read at every
500 ms poll — the queries are cheap, the
fanout is bounded, and the UI's existing poll
cadence absorbs it. Measured after the query
migration: FleetWorkflow dropped from ~197 to
~90 events/delivery, DroneWorkflow from ~302 to
~169. The subsequent Redis split cut per-step
signals to DroneWorkflow as well — see
`redis_telemetry_split.md`.

## Invariants to preserve

- **Any new `@workflow.signal` on DroneWorkflow
  that mutates the state enum MUST end with
  `await self._sync_to_fleet()`** — otherwise
  the dispatcher will think a busy drone is
  still idle (or vice-versa) until the next
  state transition. The pattern in
  `update_runtime` is the reference: capture
  `prev_state`, apply mutations, sync only if
  `self._state != prev_state`.
- **Signal handlers that only mutate
  flight_plan, position, battery, signals, or
  target_point_id MUST NOT sync** — the API's
  pull keeps the UI current, and each redundant
  sync re-inflates the event cascade we just
  cut.
- **`_query_drone` in `api/server.py` must
  catch all four failure types** — `TimeoutError`,
  `WorkflowFailureError` (from
  `temporalio.client`), `WorkflowQueryFailedError`
  (also `temporalio.client`), and `RPCError`
  (from `temporalio.service`). Dropping any
  breaks the "one unresponsive drone does not
  500 the whole /fleet response" guarantee,
  which is what preserves graceful degradation
  under a drone-worker restart (see the
  `durability_constraints` memory for the
  broader "kill anything" promise).

## Import gotcha

`WorkflowQueryFailedError` lives in
`temporalio.client`, not `temporalio.exceptions`
(easy to misplace because the other workflow
error types are split across both modules).
`RPCError` is in `temporalio.service`. An
accidental `from temporalio.exceptions import
WorkflowQueryFailedError` will `ImportError`
at API startup and take the server down under
watchfiles auto-reload.
