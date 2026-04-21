---
name: "Nuxt config process.env workaround"
description: "Why nuxt.config.ts locally declares `process` instead of importing @types/node"
type: project
---

# Nuxt config process.env workaround

`frontend/nuxt.config.ts` declares `process` inline
(`declare const process: { env: Record<string, string | undefined> }`)
instead of pulling in `@types/node`.

**Why:** `pnpm typecheck` failed with TS2591 on
`process.env.NUXT_PUBLIC_API_BASE` because
`.nuxt/tsconfig.node.json` sets `"types": []`. The
project has no other Node-ish code in the frontend,
so adding `@types/node` as a devDependency is
overkill. The local declaration is enough to
satisfy the compiler without pulling in the full
Node typings surface.

**How to apply:** If you later add code that
actually needs Node globals beyond `process.env`
(fs, path, Buffer, etc.), swap the inline declare
for a real `@types/node` dependency — the local
stub will not scale.
