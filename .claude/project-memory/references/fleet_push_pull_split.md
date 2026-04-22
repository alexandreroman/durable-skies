---
name: "Fleet push/pull split — transitions to Redis, snapshots via query"
description: "Drones publish state-enum transitions to Redis (availability hash); the dispatcher reads Redis and the API pulls DroneWorkflow queries for live snapshots"
type: project
---

# Fleet push/pull split — transitions to Redis, snapshots via query

FleetWorkflow no longer receives drone state via
signals, and no longer maintains a `self._drones`
registry. The flow now splits along three paths:

- **Pushed** from DroneWorkflow to **Redis**
  (`fleet:availability` hash, written through
  `write_drone_availability` local activity):
  only on **state-enum transitions** (IDLE →
  DISPATCHED → IN_FLIGHT → DELIVERING →
  RETURNING → IDLE, plus INCIDENT when it fires,
  and the IDLE ↔ CHARGING threshold crossing).
  The dispatcher in FleetWorkflow reads this
  hash at dispatch time via
  `read_drone_availabilities` (also a local
  activity) — so the fleet singleton stays
  stateless w.r.t. the drone list.
- **Pulled via Temporal query** by the API at
  `GET /fleet` time: `flight_plan`, `state`,
  `signals`, `current_order_id`,
  `target_point_id`. The API fires per-drone
  queries in parallel (`asyncio.gather`, 2 s
  `asyncio.wait_for` each) and merges. The
  drone list itself comes from
  `world.initial_drones()` at API startup —
  **not** from the fleet workflow.
- **Pulled via Redis** at the same moment:
  `position` and `battery_pct` via
  `telemetry.py`, `events` via `events.py`. See
  `redis_telemetry_split.md` for those streams.

**Why:** position/battery update every nav step
(~2 s) and drone state transitions fire ~5 times
per delivery. Pushing either via `update_drone`
signal used to dominate event growth on
FleetWorkflow (the singleton bottleneck).
Queries don't emit history events, and Redis
costs zero Temporal events. Measured at
variant 2 rollout: FleetWorkflow dropped from
~90 → 45 events per delivery; DroneWorkflow from
~169 → 120.

## Invariants to preserve

- **Any new `@workflow.signal` on DroneWorkflow
  that mutates a dispatch-eligibility field MUST
  end with `await self._publish_availability()`** —
  otherwise the dispatcher will think a busy or
  paused drone is still idle (or vice-versa) until
  the next transition. The dispatch-eligibility
  fields today are `self._state` and
  `self._paused` (both read by the `dispatchable`
  filter in `fleet.py`). Capture the previous
  value, apply mutations, then publish only when
  it actually changed. `update_runtime` does this
  for state; `pause_drone` / `resume_drone` do it
  for `_paused` (they early-return when already
  in the target state, so a publish implies a
  real transition).
- **Signal handlers that only mutate
  flight_plan, position, battery, signals, or
  target_point_id MUST NOT publish** — the API's
  pull keeps the UI current, and each redundant
  Redis write still costs 1 marker event on
  DroneWorkflow (local activity overhead).
- **If a new dispatch-eligibility field is added
  to `DroneAvailability` (beyond `state` and
  `paused`), every signal that mutates it must
  also call `_publish_availability()`, and the
  CAN args list in `run()` must thread the field
  through — otherwise it resets on every
  continue-as-new.
- **Do NOT filter on `updated_at` in
  `read_drone_availabilities`.** A staleness
  filter defeats the "write only on enum
  transition" optimization — see
  `staleness_filter_antipattern.md` for the
  full incident.
- **`_query_drone` in `api/server.py` must
  catch all four failure types** —
  `TimeoutError`, `WorkflowFailureError` (from
  `temporalio.client`), `WorkflowQueryFailedError`
  (also `temporalio.client`), and `RPCError`
  (from `temporalio.service`). Dropping any
  breaks the "one unresponsive drone does not
  500 the whole /fleet response" guarantee,
  which is what preserves graceful degradation
  under a drone-worker restart.
- **Dispatcher defer loop.** When
  `read_drone_availabilities` returns an empty
  list (Redis down, or genuinely no dispatchable
  drones), FleetWorkflow sleeps 2 s then
  retries. The "waiting" event is emitted only
  once per drought, guarded by a
  `_waiting_for_drone` flag — do not remove the
  flag or the event log will flood.

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

## Historical note

Before variant 2, transitions were pushed to
FleetWorkflow via an `update_drone` signal and
the fleet held a `self._drones` dict. That
handler + dict + the `initial_drones` CAN slot
were all removed. If you see references to
`update_drone` in older memory notes or
comments, they are obsolete.
