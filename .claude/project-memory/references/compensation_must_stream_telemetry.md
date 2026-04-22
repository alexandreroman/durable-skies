---
name: "Compensation paths must stream telemetry, not teleport"
description: "Recovery/compensation paths that move a drone must drive it through a real flight activity streaming per-step Redis telemetry — never a sleep + workflow-position teleport"
type: feedback
---

# Compensation paths must stream telemetry, not teleport

When `DeliveryWorkflow`'s compensation saga moves
a drone (`ACTION_ABORT`, `ACTION_EMERGENCY_LAND`,
`ACTION_DIVERT_RECHARGE`, or any future recovery
action), it MUST drive the drone through a real
activity that streams position/battery to Redis on
every step — modelled on `fly_drone_to_base` in
`activities/drone.py`. It MUST NOT just signal a
new state, `workflow.sleep(...)`, and teleport to
the final position in `_finalize`.

**Why:**

- `frontend/app/components/FleetMap.vue` filters
  drones out of the canvas render for states
  `IDLE`, `CHARGING`, and `COMPLETED` (see the
  `continue` guard at the top of the drone draw
  loop and the hit-test loop). A drone in those
  states is simply not drawn.
- `DroneWorkflow._position` is only initialized
  to `home_location` (see
  `workflows/drone_entity.py::run`) and is
  otherwise not updated during a normal
  `navigate_drone` flight — `navigate_drone`
  writes position only to Redis telemetry, never
  via `update_drone(position=...)`.
- `api/server.py::_overlay_telemetry` puts the
  Redis position on top of the workflow position,
  with a 10 s Redis TTL (see
  `_TELEMETRY_TTL_S` in `telemetry.py`).
- Combined effect of a naïve compensation: it
  flips `state=RETURNING`, sleeps, flips
  `state=COMPLETED` with
  `position=home_location`, and returns. The UI
  sees the drone frozen wherever Redis last had
  it (the crash coordinate) for 10 s, then the
  workflow position snaps to home, the state
  snaps to COMPLETED, and the filter hides it.
  From the user's perspective the drone never
  flies home — it disappears in place. That was
  the original "drone disappears instead of
  flying home" bug.

**How to apply:**

- When adding a new recovery action to
  `DeliveryWorkflow`, or any compensation path
  elsewhere, route it through an activity that
  loops `write_drone_telemetry` +
  `activity.heartbeat` + `asyncio.sleep` per
  step. Model it on `fly_drone_to_base`
  (`activities/drone.py`) — reuse the `_NAV_STEPS
  / _NAV_STEP_DELAY_S / _BATTERY_PER_STEP /
  _lerp` constants so the cadence matches normal
  flight.
- Keep `state=RETURNING` (or another state that
  is NOT in the FleetMap filter) for the whole
  duration of the streamed flight. The moment
  you flip to `COMPLETED` the drone vanishes.
- Only flip to `COMPLETED` in `_finalize` after
  the stream has ended — this is what lets the
  drone's disappearance at the base read as "it
  arrived and landed" instead of "it teleported
  and vanished".
- Do NOT touch `DroneWorkflow._position`
  mid-flight as a shortcut to "look like it's
  flying". The Redis overlay covers the tween;
  workflow position is only the fallback.
- Recovery activities must NOT advance the
  flight plan legs (no `advance_leg`) and must
  NOT inject further incidents — `fly_drone_to_
  base` documents both points.
