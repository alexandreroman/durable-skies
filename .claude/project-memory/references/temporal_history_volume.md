---
name: "Temporal history volume invariants for nav cadence and long-lived CAN"
description: "Design invariants to preserve when tuning navigate_drone constants or adding state to FleetWorkflow / DroneWorkflow"
type: project
---

# Temporal history volume invariants for nav cadence and long-lived CAN

Two invariants keep Temporal history manageable
on the long-lived entity workflows:

## 1. `navigate_drone` cadence triplet is coupled

`activities/drone.py` exposes three constants
that must move together:

- `_NAV_STEPS × _NAV_STEP_DELAY_S = total leg
  duration` (currently 12 s)
- `_NAV_STEPS × _BATTERY_PER_STEP = total leg
  drain` (currently 12%)

The battery-critical incident only fires when
`battery < 25%` during the first half of a
`to_target` leg (progress < 0.5). The documented
test scenario starts a drone at battery=28% and
relies on step 2 crossing the 25% threshold.
Changing any one of the three constants in
isolation either breaks the incident trigger
(too little drain) or stops the UI from seeing
intermediate positions (too few steps).

**Why:** cutting the cadence 4× (24→6 steps)
reduced Temporal events by ~54 per delivery per
workflow, but the only reason the low-battery
demo still works is that drain was bumped 4×
at the same time.

**How to apply:** when asked to tune smoothness
or flight duration, adjust the triplet as a unit.
Write the new values down alongside the
corresponding "total drain" and "total
duration" so a reviewer can spot a broken
invariant immediately. Re-verify with the
battery=28% mental trace (or an actual test) if
either total changes.

## 2. Adding state to FleetWorkflow requires extending its CAN payload

`FleetWorkflow.run` takes optional `initial_*`
args (currently just `initial_pending` —
`initial_events`, `initial_drones`, and
`initial_next_drone_idx` were removed when the
event log + drone registry moved to Redis; see
`redis_telemetry_split.md` and
`fleet_push_pull_split.md`) and the CAN call at
the top of the run loop reconstructs state from
them. Every field added to `__init__` that
carries meaningful state across deliveries MUST
also be:

1. added as an optional `initial_*` arg on
   `run()` with a sensible default,
2. restored at the top of `run()` when
   provided,
3. included in the `args=[...]` list passed to
   `workflow.continue_as_new`.

`DroneWorkflow` has the same invariant on a
smaller scale: `self._battery_pct` now carries
across missions (progressive charging lives in
the entity, not the delivery child), so its CAN
call passes `self._battery_pct` as the last
positional arg and `run()` accepts it via
`initial_battery_pct: float = 100.0`. Any future
cross-mission entity state (per-drone odometer,
cumulative hours, etc.) must be threaded through
CAN the same way. See
[progressive charging + 40% dispatch gate](progressive_charging_and_dispatch_gate.md).

**Why:** silently adding a new field (say, a
per-order metrics counter) without threading it
through CAN would cause the field to reset to
its default every ~25 deliveries when the fleet
CAN fires — a classic "works on my short demo,
breaks overnight" bug.

**How to apply:** treat the `initial_*` params
on `FleetWorkflow.run` as a checklist. If you
touch `__init__`, search for `continue_as_new`
in the same file and make sure the new field is
in all three places above. The dispatcher's
view of which drones exist is rebuilt per-cycle
from the `fleet:availability` Redis hash (sorted
by `drone_id` for deterministic replay), so
there is no `_drone_order` state to thread.

## Threshold choice

`_HISTORY_THRESHOLD = 2000` in both workflows
is tuned for **demo visibility** — CAN fires
roughly every 7 deliveries per drone so a
Temporal-UI audience sees rotation happen. Live
measurements: one delivery adds ~300 events to
DroneWorkflow and ~200 to FleetWorkflow. For a
longer-running deployment, bumping to ~10 000
reduces rotation noise without risking the
50 k / 50 MB warning.

## 3. Retrofitting CAN onto long-lived workflows breaks replay

If a long-lived workflow instance already has
history ≥ threshold when the CAN branch is
first deployed, its next replay will try to
issue a `continue_as_new` command at an event
where the old history shows a different command
(typically a `SignalExternalWorkflowExecution`
emitted by an activity-originated drone update).
The worker fails with:

```
Nondeterminism error: Continue as new workflow
machine does not handle this event:
HistoryEvent(id: N, SignalExternalWorkflowExecutionInitiated)
```

**Why:** `workflow.info().get_current_history_length()`
is replay-safe (returns the right value at each
replay point), but the *branch* it gates is not
backward-compatible with histories that already
crossed the threshold without CANning.

**How to apply:** either

a. Use `workflow.patched("…")` to guard the CAN
   branch (new runs get the marker, old replays
   see no marker → skip branch). Python-specific
   caveat: `patched()` memoizes on first call,
   so an old run that replays it once returns
   `False` forever and never CANs on its own —
   it unsticks but needs a terminate+restart
   (or a very long natural end) to benefit from
   CAN.
b. For demo contexts, the simpler path is
   `temporal workflow terminate --query
   'ExecutionStatus="Running"'` then
   `touch backend/src/durable_skies/api/server.py`
   to trigger the API lifespan to respawn the
   fleet + drones fresh. State is reset to home
   base / 100% battery, which matches the demo's
   IDLE invariants anyway.

Prefer (b) during the prototype phase where
terminating is cheap. Switch to (a) once drones
are expected to survive across code
deployments.
