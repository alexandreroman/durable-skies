# Project Memory

> When a new decision **contradicts** an existing
> memory note, do NOT silently override it.
> Instead: surface the conflict, quote the
> existing memory, explain how the new decision
> differs, and ask for explicit confirmation
> before updating. **Do NOT take any action** —
> no tool calls, no file writes — until confirmed.

- [Frontend is backend-driven via /fleet polling](references/frontend_is_backend_driven.md) — useFleet.ts polls GET /fleet every 500 ms; no client-side simulation
- [Nuxt config process.env workaround](references/nuxt_config_process_workaround.md) — nuxt.config.ts inlines `declare const process` instead of depending on @types/node
- [Per-drone entity workflow architecture](references/architecture_drone_entity.md) — FleetWorkflow aggregates, DroneWorkflow owns per-drone state + FlightPlan, DeliveryWorkflow is a child per order
- [Worker-restart durability constraints](references/durability_constraints.md) — heartbeat_timeout on heartbeating activities + asyncio.wait_for on /fleet query are load-bearing for "kill anything" recovery
