# Changelog

All notable changes to this project are documented here. Format loosely
follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added
- **Autonomous canary rollouts** (`/api/v1/rollouts`, Rollouts page): traffic
  for an application's un-pinned `/generate` requests is split between an
  incumbent and a challenger model, and a worker loop advances, promotes, or
  rolls back from the challenger's real error rate, evaluated quality (an
  absolute floor plus a regression budget relative to the incumbent over the
  same window), and model health, alerting through the existing webhook path.
  A partial unique index guarantees one active rollout per application.
- **Multi-replica-safe worker loops**: each periodic pass takes a Postgres
  advisory lock (`core/locks.py`, design decision 12); operator actions and
  worker passes serialise on the rollout row.
- **Worker observability**: the worker serves its own `/metrics`
  (`SENTINEL_WORKER_METRICS_PORT`, default 9100) with per-loop pass/duration/
  last-success metrics, `sentinel_queue_depth`, and counters for rollout
  decisions, fired alerts, and model status changes.
- **Monitoring stack**: `docker compose --profile monitoring up` runs
  Prometheus (scraping the API and every worker replica) and Grafana with a
  provisioned dashboard; `alert_rules.yml` gains a `sentinellm.autonomy` group.
- Demo seed now leaves a real canary rollout in flight (`checkout-assistant`).
- Frontend tests for the Rollouts page, Models page health controls, and the
  API client (13 → 40 tests), via a small fetch-router helper.
- Earlier feature rounds (see git history): experiments run/compare, dataset
  import, configurable alert rules, prompt promotion gate, model catalog CRUD,
  trace feedback / full-text search / tags / CSV export / replay, cache
  observability, per-application cost budgets, automatic model health
  detection, Slack-compatible webhooks, and per-API-key application scoping.
- `.dockerignore` at the repo root and in `frontend/` — the `api`/`worker`
  images no longer ship `.venv` (~300MB) into the build context, and the
  `frontend` image no longer risks `COPY . .` overwriting its freshly
  installed `node_modules` with whatever happens to be on the host.
- SDK test coverage (`tests/unit/test_sdk_client.py`, respx-mocked at the
  HTTP boundary): `sentinellm.sdk.client` goes from 0% to 100% covered —
  request shape, header, span serialization, and HTTP-error propagation
  for both `submit_trace` and `generate`.
- This changelog.

### Fixed
- `sentinel_evaluation_score` was recorded in the worker process but only the
  API served `/metrics`, so the metric was always empty; it is now served by
  the worker. `sentinel_queue_depth`, referenced by the Kubernetes docs, did
  not exist and now does.
- A scoped API key could mint an unscoped key for its own application, and the
  CSV export was open to formula injection (CWE-1236).
- The 422 handler crashed on a `ValueError` raised from a Pydantic
  cross-field validator.
- Rollout evaluation discarded thin evidence windows and could persist one
  rollout's cursor when another rollout committed in the same pass; both fixed
  (regression-tested).

### Deprecated
- `GenerateRequest.use_router` never had any effect; it is now marked
  deprecated in the API schema. Set `preferred_model` to bypass routing.

### Changed
- The four hand-copied worker loops now share one runner (`worker/periodic.py`)
  that adds the lock, metrics, and a guarantee no exception can kill a loop.
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
