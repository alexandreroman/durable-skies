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
- [Agents only at decision points](references/agent_placement_at_decision_points.md) — dispatcher + anomaly handler only; mission is deterministic, no per-drone pilot agent
- [Battery threaded for anomaly triggering](references/battery_threading_for_anomaly.md) — DroneWorkflow passes self._battery_pct into DeliveryWorkflow so battery_critical can actually fire
- [Long-lived workflow signature migration](references/workflow_signature_migration.md) — adding required args to FleetWorkflow/DroneWorkflow.run needs optional defaults or terminate+restart
- [Temporal history volume invariants](references/temporal_history_volume.md) — nav cadence triplet must move together; new FleetWorkflow state must be threaded through the CAN payload
- [Fleet push/pull split](references/fleet_push_pull_split.md) — drones push state-enum transitions only; API pulls flight_plan/state/signals from each DroneWorkflow at /fleet time
- [Redis telemetry split](references/redis_telemetry_split.md) — position/battery live in Redis (10s TTL), not Temporal; telemetry writes must never raise and RETURNING state moves with DeliveryWorkflow
- [Progressive charging + 40% dispatch gate + CHARGING state](references/progressive_charging_and_dispatch_gate.md) — battery carries via DroneWorkflow sleep loop; dispatcher filters on > 40%; at-home drones split IDLE/CHARGING
