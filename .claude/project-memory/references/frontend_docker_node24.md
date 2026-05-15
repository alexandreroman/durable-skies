---
name: "Frontend Dockerfile pinned to node:24-slim"
description: "Frontend Dockerfile builder and runner stages must stay on node:24-slim (or newer LTS)"
type: project
---

# Frontend Dockerfile pinned to node:24-slim

The `frontend/Dockerfile` builder and runner stages
use `node:24-slim`. Do not downgrade to Node 20 or
21.

**Why:** corepack resolves pnpm 11.1.2, which
imports the `node:sqlite` built-in module
introduced in Node.js 22. Building on Node 20
fails at `pnpm install` time. Node 24 is the
current active LTS (since October 2025), which
matches the CLAUDE.md "latest LTS" rule.

**How to apply:** when bumping the base image,
move forward to a newer LTS (Node 26 once it
goes active), never backward. If a future pnpm
or Nuxt upgrade reintroduces a build failure,
check the pnpm release notes for new Node
built-in module usage before changing the base
image.
