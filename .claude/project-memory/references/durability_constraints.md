---
name: "Worker-restart durability constraints"
description: "Design rules that keep the 'restart any component anytime' demo promise intact, uncovered during live kill-the-worker testing"
type: project
---

# Worker-restart durability constraints

Two hard rules keep the stack recoverable when
the worker, API, or UI container is killed at
any moment:

1. **Any long-running activity that heartbeats
   MUST set a `heartbeat_timeout`** on its
   `activity_tool` wiring (or
   `start_to_close_timeout` alone must be
   short). Without it, when the current worker
   dies mid-activity, Temporal waits out the
   full `start_to_close_timeout` before
   re-dispatching — up to 5 minutes of visible
   "frozen drones" in the UI.
2. **Any Temporal query exposed through the
   FastAPI gateway MUST be wrapped in
   `asyncio.wait_for(...)`** with a short
   timeout (≤ 2 s) and surface a 503 on
   timeout. Queries need a live worker to
   respond; an unbounded `await handle.query()`
   hangs the request (and therefore the UI's
   500 ms poll loop) during a worker restart.

**Why:** The demo's value proposition is
"durable — kill anything and it keeps going."
Without rule 1, `navigate_drone`'s
`start_to_close_timeout=5min` caused 5/6 drones
to sit idle for ~5 minutes after a mid-flight
kill (observed via
`PENDING_ACTIVITY_STATE_STARTED` attempt 1 in
the Temporal history API). Without rule 2,
`GET /fleet` blocked forever while the worker
was down, freezing the UI instead of degrading
gracefully. The fix cut end-to-end recovery
from "5 min+" to "91 s from kill to all 6
orders delivered."

**How to apply:**

- When adding a new activity that loops/sleeps
  for more than a couple of seconds **and**
  emits `activity.heartbeat(...)`, pass a
  `heartbeat_timeout` to the `activity_tool(...)`
  call — rule of thumb: 10× the heartbeat
  interval.
- When adding a new `GET` endpoint in
  `api/server.py` that fans out to a Temporal
  query, always wrap the `handle.query(...)`
  call in `asyncio.wait_for` and map
  `TimeoutError` to `HTTPException(status_code=503)`.
- Short activities (≤ 2 s body, 30 s
  `start_to_close_timeout`) can skip
  `heartbeat_timeout` — a 30 s worst-case
  recovery lag is acceptable and was kept
  intentional for `takeoff_drone`,
  `land_drone`, `pickup_package`,
  `dropoff_package`.
- Temporal workflows themselves are already
  durable for free — these rules only cover
  the activity and query surfaces where the
  default timeouts were too permissive for a
  500 ms-poll UI.
