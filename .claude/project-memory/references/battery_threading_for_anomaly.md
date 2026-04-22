---
name: "Battery threaded from DroneWorkflow into DeliveryWorkflow to enable anomaly triggering"
description: "Why DeliveryWorkflow.run takes battery_start_pct from the drone entity instead of hardcoding 100%"
type: project
---

# Battery threaded from DroneWorkflow into DeliveryWorkflow to enable anomaly triggering

`DeliveryWorkflow.run` takes a `battery_start_pct`
parameter (positioned between `order` and
`model_name`). `DroneWorkflow` passes
`self._battery_pct` when it spawns the delivery
child. The first `navigate_drone` activity call
uses that value as `battery_start_pct`; the
subsequent nav calls thread the returned battery
forward within the mission.

**Why:** without this, the first nav always
started at 100% and the `battery_critical`
branch inside `navigate_drone` (fires when
`battery < 25%` on the first half of a
`to_target` leg) could never trigger in a clean
single-mission run — the anomaly handler agent
was effectively dead code end-to-end. Threading
the real battery also lets you *test* the
anomaly path by manually signaling a drone
to a low battery via
`update_runtime {"battery_pct": 28}` and then
forcing that drone to be picked (e.g. by
staging the others as `DISPATCHED`). Battery
now also carries across missions — see
[progressive charging + 40% dispatch gate](progressive_charging_and_dispatch_gate.md).

**How to apply:** keep the `battery_start_pct`
thread intact when touching
`DeliveryWorkflow.run` or the
`execute_child_workflow(DeliveryWorkflow.run,
args=[...])` call site in `DroneWorkflow`. Any
future cross-mission battery carryover or
recharge-and-resume logic hooks in here.
