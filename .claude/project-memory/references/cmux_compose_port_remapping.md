---
name: "cmux per-workspace compose port remapping"
description: "cmux worktrees auto-generate a compose.override.yml that offsets all host ports from $CMUX_PORT"
type: project
---

# cmux per-workspace compose port remapping

Each isolated cmux workspace runs its own Docker
Compose stack on a per-workspace port block. The
`.cmux/post-create.sh` hook generates a
`compose.override.yml` in the new worktree (and
`.cmux/pre-destroy.sh` tears the stack down). The
override is gitignored and never committed.

Host-port map, based at `$CMUX_PORT` (cmux assigns
each workspace a contiguous block, e.g. 9150–9159):

- frontend / web UI: `$CMUX_PORT`
- temporal gRPC: `$CMUX_PORT + 1`
- temporal UI: `$CMUX_PORT + 2`
- api: `$CMUX_PORT + 3`
- redis: `$CMUX_PORT + 4`

**Why:** parallel cmux workspaces otherwise collide
on the fixed host ports (3000, 7233, 8233, 8000,
6379) declared in `compose.yml`.

**How to apply:**

- The override uses the `!override` YAML tag on every
  `ports:` list — required because Compose *appends*
  to port lists instead of replacing them. Needs
  Docker Compose v2.24+ (project runs v5.1.3).
- `temporal` and `redis` have hardcoded
  `container_name` in `compose.yml`; the override
  suffixes them with the workspace slug so containers
  don't clash. Internal service DNS (`temporal:7233`)
  is unaffected — it resolves via the service name.
- `frontend.NUXT_PUBLIC_API_BASE` is repointed to the
  remapped API host port because it is browser-evaluated.
- Only covers the full Docker stack path (`make
  app-up` / `make infra-up`). The host hot-reload path
  (`make dev`/`worker`/`api`/`ui`) runs host processes
  that read `localhost:7233`/`:8000` and is NOT isolated
  by this override.
