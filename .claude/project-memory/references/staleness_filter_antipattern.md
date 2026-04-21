---
name: "Staleness filters are incompatible with minimal-push writers"
description: "Why the 60 s staleness filter on Redis fleet availability was removed, and the general rule that readers must not filter on freshness when writers only push on state change"
type: feedback
---

# Staleness filters are incompatible with minimal-push writers

Do not add an `updated_at`-based staleness
filter to any Redis registry whose writer only
publishes on state change. They cancel each
other out and silently strand the system.

**Why:** during variant 2 rollout (moving drone
availability from FleetWorkflow state into the
Redis `fleet:availability` hash), the reader was
initially set up to skip entries older than
`_STALE_AFTER_S = 60`. The writer publishes only
on state-enum transitions (the whole point of
the optimization — minimise events). Result: a
drone sitting IDLE for 61 s ceases writing,
falls past the cutoff, and vanishes from the
dispatcher's view. Live repro: 20 orders queued,
4 drones all IDLE at 100 %, dispatcher logging
`⌛ Dispatcher waiting: no available drone` in an
endless polling loop. The fix was to delete the
filter — the defensive rationale ("drop crashed
drones") didn't hold up under the actual failure
modes:

- Worker down → the DroneWorkflow is paused by
  Temporal, not dead. `assign_order` signals are
  durable in Temporal's queue and delivered when
  the worker resumes. Nothing is lost, nothing
  needs filtering.
- DroneWorkflow truly terminated → the next API
  lifespan startup re-registers the drone and
  rewrites its availability entry. The stale
  record is overwritten, not left dangling.
- Redis itself down → `hgetall` raises and the
  reader returns `[]` anyway. No filter needed.

So the filter protected against no real scenario
and actively broke the common path.

**How to apply:**

- When writer cadence is "on change only", the
  reader must trust the last written value
  indefinitely. Either the drone is alive (its
  next transition will refresh), or it's gone
  (terminated drones get rewritten on respawn).
- If you think a freshness guard is needed,
  reach for one of these instead — never a read
  filter:
  - **Tombstones**: writer explicitly `HDEL`s
    its field on graceful shutdown (e.g. the
    DroneWorkflow's `shutdown` signal).
  - **Periodic heartbeat**: writer republishes
    on a timer. This re-introduces Temporal
    timer events, partially defeats the
    minimal-push optimization, and should be
    justified by a concrete reliability
    requirement — not a hunch.
  - **Key-level TTL**: use individual keys
    (`drone:{id}:availability`) with Redis TTL,
    refreshed by heartbeat. Same trade-off as
    above, plus loses the single-HGETALL read
    shape.
- If you find yourself adding a filter "just to
  be safe", stop. Write down the specific
  failure mode you are guarding against, then
  check whether the Temporal + lifespan
  contract already handles it.

## Scope

This rule applies to **any** Redis-backed
registry in durable-skies where the writer is
optimised for minimal events:

- `fleet:availability` (drone registry read by
  the dispatcher) — covered above.
- `drone:{id}:telemetry` (position + battery) —
  writer *is* high-frequency (every 2 s during
  flight), so the 10 s TTL is fine. This memory
  is specifically about minimal-push writers.
- `fleet:events` (event log) — append-only list,
  no reader filter, not affected.

If a future registry is introduced with a
minimal-push writer, apply the rule above.
