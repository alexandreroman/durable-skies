---
name: "Adding required args to long-lived singletons needs a terminate+restart migration"
description: "Gotcha: changing @workflow.run signature on FleetWorkflow / DroneWorkflow breaks running instances until terminated"
type: feedback
---

# Adding required args to long-lived singletons needs a terminate+restart migration

When you add a required positional argument to a
`@workflow.run` method of a long-lived workflow,
the currently-running instance becomes
unactivatable: the worker repeatedly fails with
`TypeError: ... missing 1 required positional
argument: '<name>'` and spams the log roughly
every 600ms until the stale workflow is
terminated.

**Why:** observed when `FleetWorkflow.run` gained
`model_name` as a required arg. The API's
`lifespan` hook correctly called
`start_workflow(..., args=[settings.anthropic_model], ...)`
for fresh startups, but it treated
`WorkflowAlreadyStartedError` as a silent no-op,
so the old instance kept running with its old
signature and the worker kept trying to replay
it with code that now demanded the new arg.

**How to apply:** any time you change the
signature of `@workflow.run` on:

- `FleetWorkflow` (singleton id `fleet-supervisor`)
- `DroneWorkflow` (long-lived ids like
  `drone-alpha`, `drone-bravo`, …, one per entry
  in `world._DRONE_ASSIGNMENTS`)
- any future long-lived singleton

…pick one of:

a. Make the new arg **optional with a default**
   and read it from a signal or settings on
   first use. Backward-compatible, no migration
   needed.
b. Plan a deliberate **terminate + restart**:
   terminate the stale workflow via the Python
   client (or `temporal workflow terminate`),
   then let the API's `lifespan` recreate it
   (restart the API, or call
   `start_workflow` directly) with the new
   signature.

`DeliveryWorkflow` and `OrderWorkflow` are
per-order and short-lived, so their signatures
can change freely — any in-flight one will
finish under the old shape and the next one
starts fresh.
