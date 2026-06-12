#!/usr/bin/env bash
set -euo pipefail

# cmux pre-destroy hook: tear down this workspace's Docker stack before the
# worktree is removed. Best-effort — a teardown failure must never abort the
# worktree removal. Runs with cwd = the worktree root.

if [[ -f compose.override.yml ]]; then
  echo "Tearing down this workspace's Docker stack..."
  docker compose down -v --remove-orphans || true
  rm -f compose.override.yml
else
  echo "No compose.override.yml found — nothing to tear down."
fi
