---
name: "Frontend is backend-driven via /fleet polling"
description: "The Nuxt UI renders only what the Temporal FleetWorkflow reports; there is no client-side simulation any more"
type: project
---

# Frontend is backend-driven via /fleet polling

The Nuxt dashboard under `frontend/app/` is a pure
view layer. `app/composables/useFleet.ts` polls
`GET ${apiBase}/fleet` every 500 ms (recursive
`setTimeout`, not `setInterval`) and assigns the
returned `FleetState` to reactive refs. There is no
local tick, no `Math.random`, no client-side state
machine — every drone position, battery level, and
event message comes from the `FleetWorkflow` query.

The backend sources the fleet fixture (3 depots, 8
delivery points, 6 drones named Alpha..Foxtrot) from
`backend/src/durable_skies/world.py` and returns it
inside the same `/fleet` payload so the UI does not
duplicate that data.

**Why:** An earlier version simulated the lifecycle
client-side because the backend did not stream state.
That caused divergence between what the UI showed
and what Temporal actually executed. The refactor
makes Temporal + ADK the single source of truth.

**How to apply:** Changes to fleet geometry (bases,
delivery points, drone roster) go in
`backend/src/durable_skies/world.py`. The UI picks
them up automatically. Do NOT re-introduce any tick
loop or random dispatch in `useFleet.ts`; extend the
workflows / activities instead.
