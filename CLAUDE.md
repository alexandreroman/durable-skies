# durable-skies

Durable multi-agent drone delivery demo showcasing
the Google ADK × Temporal integration.

See [README.md](README.md) for full documentation.

## Tech stack

- Python 3.12, uv, Temporal Python SDK with the
  `google-adk` extra, Google ADK, LiteLLM, Anthropic
  Claude Sonnet, FastAPI
- Nuxt 4, Vue 3, Tailwind 4, pnpm
- Local Temporal via Docker Compose

## Build & run

```bash
make install
make temporal-up
make worker     # in terminal 1
make api        # in terminal 2
make ui         # in terminal 3
```

## Modules

- `backend/` — Python package `durable_skies` with
  Temporal workflows, activities, ADK agents
  (per-drone pilot, dispatcher, route optimizer),
  and the FastAPI gateway.
- `frontend/` — Nuxt 4 dashboard: map, agent panel,
  streaming event log.

## Agents

Use the following agents (from the
[skillbox](https://github.com/alexandreroman/skillbox)
plugin) for all code tasks:

- **code-writer** — for ANY task that writes,
  modifies, or refactors code. This includes
  one-line fixes, import changes, visibility
  tweaks, and adding assertions. Never use
  the Edit or Write tools directly on source
  files — always delegate to this agent.
- **code-reviewer** — for read-only code review
  before merging or when investigating issues.

## Memory

At the start of every conversation, read
`.claude/project-memory/MEMORY.md` to load
project context from previous conversations.

Use the **project-memory** skill (from the
[skillbox](https://github.com/alexandreroman/skillbox)
plugin) proactively — without being asked — whenever
the conversation reveals project decisions, deadlines,
team context, external references, workflow preferences,
or corrective feedback worth persisting across
conversations.

**Important:** Always use the **project-memory**
skill to persist information. Never use the built-in
auto-memory system (`~/.claude/projects/.../memory/`)
for project decisions or context — it is local and
not shared with the team.

## Conventions

- Line length limits for readability:
  - Text / Markdown: 80 columns max
  - Code: 120 columns max
- Follow standard Markdown conventions: blank line
  before and after headings, blank line before and
  after lists, fenced code blocks with a language tag
- Always use the latest LTS or stable version of
  languages, frameworks, and libraries. Check the
  official documentation or use available tools
  (e.g. context7) to verify current versions before
  choosing a dependency.
- Never use compound shell commands (`;`, `&&`,
  `|`) in Bash tool calls — this applies to
  every Bash tool invocation Claude makes during
  a conversation, not just code in documentation.
  Each command must be a separate Bash tool call.
- ADK agents must stay deterministic inside
  Temporal workflows: do not call `time.time()`,
  `uuid.uuid4()`, or make direct network I/O from
  workflow code. Wrap LLM calls via `TemporalModel`
  (or `LiteLlm` through the ADK model registry) and
  tool calls via `activity_tool`.
- The ADK + Temporal integration is currently
  experimental — pin `temporalio[google-adk]` and
  `google-adk` versions before upgrading.
