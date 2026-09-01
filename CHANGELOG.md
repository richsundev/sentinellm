# Changelog

All notable changes to this project are documented here. Format loosely
follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added
- `.dockerignore` at the repo root and in `frontend/` — the `api`/`worker`
  images no longer ship `.venv` (~300MB) into the build context, and the
  `frontend` image no longer risks `COPY . .` overwriting its freshly
  installed `node_modules` with whatever happens to be on the host.
- SDK test coverage (`tests/unit/test_sdk_client.py`, respx-mocked at the
  HTTP boundary): `sentinellm.sdk.client` goes from 0% to 100% covered —
  request shape, header, span serialization, and HTTP-error propagation
  for both `submit_trace` and `generate`.
- This changelog.

### Changed
- All Docker base images (`python:3.12-slim`, `node:20-alpine`,
  `postgres:16-alpine`, `redis:7-alpine`) are now pinned by digest —
  in `infrastructure/docker/{api,worker}.Dockerfile`, `frontend/Dockerfile`,
  `docker-compose.yml`, and `infrastructure/kubernetes/{postgres,redis}.yaml`
  — for reproducible builds. Each pin carries a comment with the exact
  `docker pull` + `docker inspect` command to re-resolve it.

## [0.1.1] - CI fixes

- Upgraded the frontend from Next.js 14.2.15 to 16.3.3, resolving a critical
  DoS advisory and several high-severity transitive vulnerabilities
  (`npm audit --audit-level=high` now reports zero findings).
- Migrated ESLint 8 → 9 and `.eslintrc.json` → flat config
  (`eslint.config.mjs`), since Next 16 removed the `next lint` command;
  `npm run lint` now invokes `eslint .` directly.
- Fixed two real `eslint-plugin-react-hooks` findings in `lib/useFetch.ts`
  surfaced by the upgrade (a ref mutated during render; a documented,
  justified exception for the standard reset-loading-state-before-refetch
  pattern).
- Added `.gitleaks.toml` with two narrowly-scoped allowlist entries for
  known non-secret values (`demo-api-key`, the Recharts `dataKey` literal
  `p95_latency_ms`) that the default gitleaks ruleset was flagging.

## [0.1.0] - Initial platform build

Full SentinelLLM platform: provider-agnostic LLM/embedding layer with a
deterministic `MockProvider` for zero-key local operation; trace ingestion
(SDK + REST) and a `/generate` pipeline composing retrieval, an explainable
quality/cost/latency/risk router, a resilient retry/fallback LLM client,
and a semantic cache; an evaluation pipeline (8 deterministic evaluators +
LLM-as-judge with structured-output retry + modular hallucination
detection); prompt versioning, experiments, automated regression detection,
and alerting; a Next.js dashboard (13 pages); Docker Compose one-command
demo with idempotent seed data; Kubernetes manifests; 4 GitHub Actions
workflows; and the accompanying docs suite. See `README.md` and
`docs/design-decisions.md` for the full architecture.
