# syntax=docker/dockerfile:1

FROM node:20-slim AS builder

WORKDIR /app

RUN corepack enable

COPY package.json pnpm-lock.yaml ./
# Skip the `postinstall: nuxt prepare` script here — it needs nuxt.config.ts,
# which has not been copied yet. `nuxt build` runs prepare internally.
RUN pnpm install --frozen-lockfile --ignore-scripts

COPY . .
RUN pnpm build

FROM node:20-slim AS runner

WORKDIR /app

ENV NODE_ENV=production \
    HOST=0.0.0.0 \
    PORT=3000

COPY --from=builder /app/.output ./.output

EXPOSE 3000

CMD ["node", ".output/server/index.mjs"]
