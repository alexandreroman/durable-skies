---
name: "Progressive battery charging in DroneWorkflow and 40% dispatch gate"
description: "Battery carries across missions, charges progressively while idle via workflow.sleep; FleetWorkflow dispatch requires battery_pct > 40%; a drone below the threshold surfaces as CHARGING state"
type: project
---

# Progressive battery charging in DroneWorkflow and 40% dispatch gate

Battery is no longer instant. Two coupled
changes sit behind the "test battery charge /
backpressure" demo:

## 1. Progressive charging lives in `DroneWorkflow`

In `workflows/drone_entity.py`, the main `run`
loop sleeps `_CHARGE_STEP_DELAY_S = 2.0s` (via
`workflow.sleep`) and adds
`_CHARGE_STEP_PCT = 2.0` per tick while the
drone is IDLE, until battery hits 100% or a
new order arrives (or shutdown). A full
post-delivery recharge (~64% → 100%) takes
~36s — tuned for *demo visibility*, not
realism. The tick matches the nav-step cadence
(`_NAV_STEP_DELAY_S = 2s` in
`activities/drone.py`). The loop sits
*before* the `wait_condition` that blocks on
the next order, so an idle drone visibly
charges between missions. `_sync_to_fleet` is
called on every tick so the fleet snapshot
(and therefore the UI) sees the curve.

Battery is threaded through
`DroneWorkflow.run`'s
`initial_battery_pct: float = 100.0` optional
param and through its
`workflow.continue_as_new(args=[…])` as the last
positional — see
[temporal_history_volume.md](temporal_history_volume.md)
section 2 for the invariant.

### Drain must reach the drone entity

`navigate_drone` (an activity) writes battery to
Redis telemetry on every step so the UI can see
it drain live, but Redis is ephemeral (10s TTL).
The drone entity's `self._battery_pct` is
authoritative for charging and the dispatch
gate, and it is **only** updated by signals.
The activity therefore also calls
`update_drone(drone_workflow_id, battery_pct=battery)`
at two moments:

1. On the battery-critical branch, alongside
   `state=INCIDENT` and `add_signal="battery_critical"`.
2. At the end of a successful nav leg, just
   before `advance_leg`.

Without these signals the entity stays at 100%
for the whole mission, the charging loop never
ticks, and the UI appears to "snap" to 100% as
soon as the Redis TTL expires post-landing.
Any rework of `navigate_drone` or the signal
cadence must keep the drone entity's battery in
sync with the activity's local `battery` value.

### Idle-time battery drop also re-enters the charging loop

`DroneWorkflow.run`'s outer
`wait_condition` (used when battery is already
100% and waiting for an order) wakes on
`battery_pct < 100.0` too, followed by a
`continue` that re-enters the inner charging
loop. Without this, a test-scenario
`update_runtime {"battery_pct": 20}` signal on
a fully-charged idle drone would sit forever.

`DeliveryWorkflow` no longer resets battery to
100% anywhere:

- `_finalize`'s IDLE transition dropped the
  `battery_pct: 100.0` key.
- The `ACTION_DIVERT_RECHARGE` branch dropped
  the instant `battery_pct: 100.0` signal, the
  "⚡ recharged at X" event, and its 1-second
  sleep (the recharge was fake).

The drone limps home on whatever battery it
has and charges progressively at home.

## 2. FleetWorkflow dispatch requires battery > 40%

`workflows/fleet.py` defines
`_MIN_DISPATCH_BATTERY_PCT = 40.0`. The filter
is applied in three places in fleet.py and
they must stay in sync:

1. The `idle_drones` list comprehension at the
   top of the run loop.
2. The `wait_condition` predicate for the "no
   eligible drone" branch (dispatcher parks
   until a drone is both IDLE and above the
   threshold — `update_drone` signals from
   charging ticks wake it).
3. The `_pick_idle_drone` round-robin fallback.

**The same 40% value is also duplicated in
`workflows/drone_entity.py`** as
`_MIN_DISPATCH_BATTERY_PCT` (with a comment
pointing back to fleet.py) — the drone entity
uses it to pick between `IDLE` and `CHARGING`
for its at-home state (see §3 below). So the
"stay in sync" invariant now covers 4 places:
3 filters in fleet.py + 1 constant in
drone_entity.py.

The dispatcher filters keep the
`battery_pct > 40` check even though a drone
below the threshold now surfaces as `CHARGING`
(and so is already excluded by the
`state == IDLE` half). The numeric check is
defence-in-depth against sync lag — do not
simplify it out.

**Why:** gives the dispatcher a meaningful
constraint to reason about and lets a burst of
orders demo backpressure. Typical post-delivery
return is ~64% (3 nav legs × 12% drain = 36%),
so the drone stays eligible for one more
dispatch and is blocked only when multiple
consecutive deliveries push it below 40%. Drop
the threshold further if the drain grows or
raise it to force blocking after every mission.

**How to apply:**

- If you add a new dispatch code path (new
  agent, manual override, etc.), repeat the
  `state == IDLE and battery_pct > _MIN_DISPATCH_BATTERY_PCT`
  check.
- If you tune the nav drain (`_BATTERY_PER_STEP`
  × `_NAV_STEPS`), re-check how many deliveries
  a drone survives before falling below the
  threshold — the demo's backpressure narrative
  depends on the relationship between drain and
  threshold.
- If you want to *force* the block for a demo,
  signal `update_runtime {"battery_pct": 35}`
  to any idle drone; the dispatcher will skip
  it until ~2s × N charging ticks bring it
  above 40% (N = ceil((40 - battery) / 2)).

## 3. At-home state splits IDLE / CHARGING

`WorkflowState` (in `models.py`) has a dedicated
`CHARGING` enum value alongside `IDLE`. Rule:

- Drone with no mission, `battery_pct <= 40` →
  `CHARGING` (not dispatchable yet).
- Drone with no mission, `battery_pct > 40` →
  `IDLE` (dispatchable; may still be climbing
  towards 100%).

The split is computed by
`DroneWorkflow._idle_state()` and applied in
**four** places — new at-home state assignments
MUST go through the helper:

1. Startup, right after `initial_battery_pct`
   is assigned (before the first
   `_sync_to_fleet`).
2. Inside the charging loop, after each +2%
   tick (the per-tick sync carries the
   transition).
3. Post-delivery cleanup — replaces the old
   unconditional `self._state = WorkflowState.IDLE`.
4. End of the `update_runtime` signal handler,
   gated on the current state being one of
   `{IDLE, CHARGING}` (never overwrite an
   in-flight state).

### Why the charging-tick sync is OK

The push/pull split memory says "signals push
only on state-enum transitions". The charging
loop is a pre-existing exception: it runs
`_sync_to_fleet` on every tick to carry the
battery curve to the UI. Adding the
`_idle_state()` recompute before each tick's
sync only means that tick may also carry the
IDLE↔CHARGING transition — no new sync paths
were introduced.

### Frontend mapping

- `frontend/app/types/fleet.ts` — `WorkflowState`
  union includes `"CHARGING"`.
- `frontend/app/composables/fleetConstants.ts` —
  `WORKFLOW_STATES.CHARGING` has amber styling
  (distinct from `IDLE`'s muted grey and
  `DISPATCHED`'s brighter amber).
- `frontend/app/components/FleetMap.vue` —
  `CHARGING` is treated like `IDLE`: excluded
  from the legend, skipped in flight-plan
  rendering, skipped in the drone click-hit
  loop (a charging drone has no flight plan
  and is parked at its home base).
