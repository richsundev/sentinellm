# Changelog

All notable changes to this project are documented here. Format loosely
follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added
- **Prompt serving and autonomous prompt canaries** (decision 13). `/generate`
  with `prompt_id` + `prompt_variables` renders the registry template
  server-side — the pinned `prompt_version`, else the newest production
  version — and sends it as the system prompt; the trace records the version
  and the exact rendered text (`GET /traces` now returns `prompt_id` /
  `prompt_version`), and replay re-renders (so a different version really
  changes the answer). `POST /prompts/{id}/versions/{v}/render` previews a
  template; new versions derive/validate their declared variables. Experiments
  are served through the same path, which also removes a bug where the context
  reached the model twice.
  `/api/v1/prompt-rollouts` (Rollouts page → *Prompt canaries*) splits an
  application's prompt traffic between an incumbent and a challenger version;
  a worker loop (`prompt_rollout`) advances, promotes, or rolls back on the
  same guard rails as the model canary — now shared in
  `services/rollout_policy.py` — and rolls back immediately if the challenger
  version is deprecated. New migration `c8f4a2d91e07`, metric
  `sentinel_prompt_rollout_decisions_total`, alert
  `SentinelPromptRolloutAutoRolledBack`, and a prompt canary in the demo seed.
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
- **Fourth bug audit.**
  - *Cost alerts*: `daily_cost` and every application's `daily_cost_budget`
    were compared with the spend of the trailing **hour**, so a $50/day budget
    only alerted past $50 in a single hour (~$1,200/day). Spend is now measured
    over 24h, aggregated in SQL, and no longer skipped when the last hour was
    quiet.
  - *Worker*: an exception while claiming an evaluation job (a dropped DB
    connection) escaped the consumer loop and took every worker loop down with
    it; alert webhooks that answered 4xx/5xx counted as delivered, and a
    mistyped webhook URL (`httpx.InvalidURL`) aborted the pass that was about to
    persist the alert.
  - *Prompts*: `POST /prompts/{id}/versions/{v}/…` took an unbounded integer
    (500 on overflow); templates and declared variables are bounded; a canary
    can't be started with a deprecated challenger (the worker would have rolled
    it back on its first pass).
  - *Seed*: `scripts/seed_demo.py --force` crashed on the model catalog's
    unique constraint; it now clears the demo's own data (and only that) and
    reseeds. Regression output no longer prints a degradation as `+8.3%`.
  - *Frontend*: numeric forms (model registration, model and prompt canaries)
    sent `null` for a blank or non-numeric field and showed a generic error —
    they now name the field; failed model status changes were silent; the trace
    page hides the router's `-1` marker score and shows *why* a model was
    excluded (outage, quality floor, context window).
  - New test: a schema-driven fuzz of every JSON write endpoint (also run
    against Postgres during the audit — 0 server errors in 1,223 requests).
- **Third bug audit** (Postgres-vs-SQLite divergences, platform edges).
  - *Inputs SQLite accepted and Postgres rejected (each a 500 in production)*:
    NUL characters in any text (now stripped from request bodies, LLM output
    and imported files; a `%00` in a URL is a 400); identifiers longer than
    their `VARCHAR(n)` column (now 422); integers beyond 32 bits, including
    `offset` (now 422).
  - *Non-finite numbers*: Python's JSON parser accepts `Infinity`/`NaN`; a
    stored infinite latency poisoned the aggregates, and the 422 for it failed
    to serialise. Rejected up front, and validation errors no longer echo the
    offending input.
  - *Platform*: `/ready` (checks the database) for the Kubernetes readiness
    probe — `/health` never failed, so a pod that lost its database stayed in
    rotation; request bodies over `SENTINEL_MAX_REQUEST_BYTES` are refused
    before parsing, and dataset import no longer loads the whole upload before
    checking its size; the unauthenticated mock webhook receiver is only
    mounted in `local`/`test`; `SENTINEL_LOG_LEVEL=info` (lowercase) crashed
    startup, and a zero worker interval was a busy loop — settings are now
    validated.
  - *Observability*: log lines from a generation or an evaluation now carry
    `trace_id` (the variable was read by the formatter and never set).
  - *Frontend*: the Datasets table shows each dataset's id (the Experiments
    form asks for it); the dataset page says how many records exist; Traces is
    highlighted on a trace's detail page.
  - New tests: a hostile-input sweep over every GET endpoint.
- **Second bug audit.** Each item reproduced with a failing test first.
  - *Model health*: a model flagged down was excluded from routing, so it
    earned no traffic and stayed down forever — it now returns to `degraded`
    once its failures leave the window. Calls that failed before a fallback
    answered are recorded (`trace_metadata.failed_attempts`) and counted, so a
    model failing behind a working fallback is finally flagged; cache hits no
    longer dilute a model's error rate. Replay no longer copies that
    bookkeeping (or rollout attribution) onto the new trace.
  - *Routing*: the context window was carried into the router and never read;
    a request that cannot fit is no longer sent to the model.
  - *Evaluation*: cosine similarity could exceed 1.0 by a rounding hair, which
    failed the judge fallback's validation and the whole evaluation job; real
    judge models that wrap their JSON in a markdown fence or a sentence no
    longer burn every retry and fall back to a meaningless score.
  - *PII*: redaction is now applied on `/generate`, replay and the semantic
    cache (previously `POST /traces` only), and to retrieved documents.
  - *API*: `/generate` rejects `top_k` outside 1–50 and an empty question;
    ingested traces are priced from the model registry like `/generate`
    traces; trace tags are bounded; `q`/`tag` search treats `%` and `_`
    literally; replaying an empty-prompt trace is a 422, not a 500.
  - *Database*: connections are pre-pinged, so a Postgres restart doesn't
    500 the first requests on every pooled connection.
  - *Frontend*: an application's cost budget could not be cleared (`undefined`
    is dropped from JSON — it must be `null`); failed budget/alert-rule saves
    were silent; an emptied alert-threshold box saved as `0` and made the rule
    fire constantly; the Traces page kept its page offset when the
    environment changed.
- **Project-wide bug audit.** Each item below was reproduced with a failing
  test first.
  - *Money and metrics*: `/metrics/cost` summed a 5,000-row sample, silently
    under-reporting spend at volume (now SQL aggregates), and averaged quality
    over *all* traces instead of the evaluated ones; `/metrics/overview` sampled
    the *oldest* 5,000 traces of the window and reported the sample size as
    `request_volume`; the HTTP middleware mislabelled unmatched routes.
  - *LLM layer*: an unconfigured provider in a fallback chain aborted the whole
    chain instead of falling through; attempts were misreported after a context
    overflow; null/garbled provider JSON crashed instead of failing cleanly;
    408/409 weren't retried; provider labels on metrics and traces were guessed
    from the model id; the judge model ignored the configured provider.
  - *Routing*: model stats ignored registry priors, mixed stale and fresh
    windows, and trusted a single sample; an unroutable request was an
    unhandled 500 (now 503).
  - *Detection*: regressions against a zero baseline produced infinite/huge
    deltas and duplicate rows; alert de-duplication crashed on a duplicate.
  - *Multi-tenancy*: scoped keys could read or change other applications'
    evaluations, routing decisions, alerts, models, prompts, datasets and
    experiments; duplicate application/dataset/trace creates were 500s (now
    409).
  - *Semantic cache*: an answer was replayed for the same question over
    *different* retrieved documents, and never expired. Entries now carry a
    context key and honour `SENTINEL_CACHE_TTL_SECONDS` (default 24h; migration
    `c3a91d7e4b25`); a worker loop prunes expired rows.
  - *Prompt construction*: a request's `system_prompt` used to *replace* its
    retrieved documents, so the model never saw the context its answer was
    then judged against; both are now sent.
  - *Evaluation queue*: a job popped by a worker that then died, or never
    enqueued because Redis was down, left its trace un-evaluated forever. A new
    `evaluation_recovery` loop repairs or re-queues them
    (`sentinel_evaluation_recovered_total`).
  - *Tracing*: `configure_tracing` was never called, so
    `SENTINEL_OTEL_EXPORTER_OTLP_ENDPOINT` did nothing. The API and worker now
    enable OpenTelemetry when it is set, with `sentinel.generate` /
    `sentinel.evaluate` spans; unset, tracing stays off.
  - *Frontend*: Overview filters and the environment selector were never sent
    to the API; regression deltas were drawn as green "+" gains and read
    `1%` as `100%`; the time-range selector appeared on pages that ignore it
    and was missing from Cost; experiment comparison collapsed same-named
    experiments and a bad prompt version silently ran v1; the evaluations
    pass rate counted verdict-less metrics as failures.
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
