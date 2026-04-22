---
name: "Freeze workflow _position at incident boundary for slow-LLM resilience"
description: "Activities that raise an incident must push the crash position through update_drone(...) so DroneWorkflow._position reflects reality once Redis TTL expires during slow anomaly-agent LLM calls"
type: feedback
---

# Freeze workflow _position at incident boundary for slow-LLM resilience

Any activity that raises an incident and
transitions a drone into `INCIDENT` state MUST
also push the incident `position` through
`update_drone(...)` to the drone entity
workflow, so `DroneWorkflow._position` holds the
real crash coordinate.

The canonical applied instance is in
`activities/drone.py::navigate_drone`, on the
`battery_critical` branch: the `update_drone(
drone_workflow_id, state=WorkflowState.INCIDENT,
position=position, battery_pct=battery,
add_signal="battery_critical")` call must keep
the `position=position` kwarg.

**Why:**

- `DroneWorkflow._position` is initialized to
  `home_location` in
  `workflows/drone_entity.py::run` and is
  otherwise not updated during a normal flight —
  `navigate_drone` writes position only to
  Redis, never via signal.
- Redis telemetry TTL is 10 s
  (`telemetry.py::_TELEMETRY_TTL_S`).
- The anomaly agent's `invoke_model` LLM
  activity can run much longer than 10 s:
  minutes in the observed failure modes
  (Anthropic API rate-limit, low credits, or
  simple slow retries). Worker restart
  mid-incident also resets the local invoke_model
  clock.
- When Redis expires while the agent is still
  thinking, `api/server.py::_overlay_telemetry`
  falls back to the workflow's `_position`. If
  that value is stale-at-home, the UI shows the
  drone "teleported home" while still in
  `INCIDENT` state — red-pulsing at the base,
  never landing, until the agent eventually
  returns and `fly_drone_to_base` kicks in. The
  user-visible symptom is "the drone is at the
  base but does not land".

**How to apply:**

- Any future activity that transitions a drone
  into a state where it is going to wait on an
  external agent, a long timer, or anything else
  that might outlast the Redis TTL must
  similarly push the real coordinate through
  `update_drone(position=...)` — the exact
  location where it parked.
- Per-step position signals during normal flight
  remain a no-go: that would blow up the
  DroneWorkflow event history. See
  `temporal_history_volume.md` for the history
  budget. Only the incident boundary needs the
  one-shot position signal — the drone is now
  stationary, so there's nothing to stream, and
  one signal gives the UI a correct fallback
  indefinitely.
- Keep `update_drone(position=...)` in the same
  call as the `state=INCIDENT` transition so
  position and state always move together —
  splitting them into two signals opens a race
  where the UI could briefly see
  `state=INCIDENT` with a stale position.
