# syntax=docker/dockerfile:1

# node:20-alpine, pinned by digest for reproducible builds — re-resolve with
# `docker pull node:20-alpine && docker inspect --format='{{index .RepoDigests 0}}' node:20-alpine`
FROM node:26-alpine@sha256:2d984a15c9b54fd0aeb608b8e0d0d83529eb34d2966db27a1fb4f1edc3d298a3 AS deps
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm install --no-audit --no-fund

FROM node:26-alpine@sha256:2d984a15c9b54fd0aeb608b8e0d0d83529eb34d2966db27a1fb4f1edc3d298a3 AS builder
WORKDIR /app
ARG NEXT_PUBLIC_API_URL=http://localhost:8000
ARG NEXT_PUBLIC_API_KEY=demo-api-key
ENV NEXT_PUBLIC_API_URL=${NEXT_PUBLIC_API_URL}
ENV NEXT_PUBLIC_API_KEY=${NEXT_PUBLIC_API_KEY}
COPY --from=deps /app/node_modules ./node_modules
COPY . .
ENV NEXT_TELEMETRY_DISABLED=1
# NEXT_PUBLIC_* vars are inlined into the client bundle at build time, so
# they must be set here (not just at `docker run`/compose `environment:`).
# The build itself never contacts the backend (client components fetch at
# runtime), so this succeeds regardless of API reachability.
RUN npm run build

FROM node:26-alpine@sha256:2d984a15c9b54fd0aeb608b8e0d0d83529eb34d2966db27a1fb4f1edc3d298a3 AS runner
WORKDIR /app
ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1

RUN addgroup --system --gid 1001 nodejs \
  && adduser --system --uid 1001 nextjs

COPY --from=builder /app/public ./public
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static

USER nextjs
EXPOSE 3000
ENV PORT=3000
ENV HOSTNAME=0.0.0.0

# Node (not curl/wget) since it's guaranteed present in this image and the
# page renders its shell server-side regardless of whether the API backend
# is reachable (data fetching happens client-side), so this only fails if
# the Next.js server itself is actually down.
HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=5 \
    CMD node -e "require('http').get('http://localhost:3000/overview', r => process.exit(r.statusCode === 200 ? 0 : 1)).on('error', () => process.exit(1))"

CMD ["node", "server.js"]
