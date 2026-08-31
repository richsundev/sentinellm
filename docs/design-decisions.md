# Design decisions

Each decision below follows the same structure: **Context** (what problem
forced a choice), **Decision** (what was picked), **Alternatives**
(what else was considered), **Tradeoffs** (what the choice costs),
**Consequences** (what it implies for the rest of the system).

## 1. PostgreSQL as the primary datastore

**Context.** The platform needs relational integrity (traces → evaluations
→ metrics is a strict hierarchy), JSON columns for semi-structured data
(retrieved documents, routing candidates), and eventually vector similarity
search at scale.

**Decision.** PostgreSQL, accessed through SQLAlchemy 2.0's async engine.

**Alternatives.** MongoDB (weaker relational integrity for a genuinely
relational domain — evaluations *belong to* traces, not "are documents
that reference" them); a pure vector DB like Pinecone/Weaviate for
everything (wrong tool for transactional writes and joins across traces/
evaluations/experiments).

**Tradeoffs.** Postgres requires a real schema and migrations (Alembic) —
more upfront ceremony than a schemaless store.

**Consequences.** pgvector becomes a natural future upgrade path for the
semantic cache and retrieval corpus (see decision 6 and
[docs/performance.md](performance.md)) without a datastore migration.

## 2. Redis as a lightweight job queue, not Celery

**Context.** Trace evaluation must not block the ingestion request (section
25 of the spec), so *something* needs to hand work from the API process to
a worker process.

**Decision.** A single Redis list (`LPUSH`/`BRPOP`) wrapped in ~40 lines
([`core/queue.py`](../src/sentinellm/core/queue.py)), consumed by a plain
asyncio loop in the worker.

**Alternatives.** Celery (the "default" choice for Python task queues);
Redis Streams (consumer groups, replay) is worth reconsidering; Kafka.

**Tradeoffs.** No task retry policy DSL, no scheduled tasks, no built-in
dead-letter queue, no admin UI (Flower) — Celery gives you all of that for
free. At real scale, and especially with more than one job type, Celery
(or Redis Streams with consumer groups for at-least-once with replay)
would earn its complexity.

**Consequences.** At-least-once delivery from `BRPOP` is fine because the
worker's evaluation write is *idempotent*: `evaluations.trace_id` has a
unique constraint and the job handler claims a trace with a guarded
`UPDATE ... WHERE evaluation_status = 'pending'` before doing any work
(see decision 10). A single queue with one consumer type is exactly the
workload where Celery's machinery is overhead, not leverage — this is
revisited the moment a second job type (e.g. scheduled dataset
re-evaluation) shows up.

## 3. Asynchronous evaluation, always

**Context.** LLM-as-judge calls and multi-evaluator pipelines take
seconds; the spec explicitly forbids running them inside the ingestion
request (section 25).

**Decision.** `POST /traces` and `POST /generate` persist the trace, enqueue
a job, and return immediately with `evaluation: null`. The dashboard shows
`evaluation_status: pending → evaluating → completed | failed`.

**Alternatives.** Synchronous evaluation with a short timeout and
best-effort partial results — rejected because it couples ingestion latency
to judge-model latency, exactly the coupling that makes production LLM
platforms fragile under judge-provider slowness.

**Tradeoffs.** The dashboard must handle a "trace exists, evaluation
pending" state everywhere it shows quality scores (it does).

**Consequences.** `scripts/seed_demo.py` runs evaluation *inline* rather
than via the queue, deliberately — the demo needs a populated dashboard
immediately after `docker compose up` without depending on the worker
having drained the queue yet.

## 4. Provider abstraction (LLMProvider / EmbeddingProvider)

**Context.** The spec requires the platform to run with zero API keys and
to support multiple providers without rewriting call sites.

**Decision.** Two small ABCs — `LLMProvider.complete()` and
`EmbeddingProvider.embed()` — with `mock`, `openai`, and `anthropic`
implementations selected by a factory keyed off settings/model-id prefix
(`"openai:gpt-4o-mini"` → `OpenAIProvider`).

**Alternatives.** A single "universal" client library (e.g. LiteLLM) —
would work, but hides exactly the retry/error-classification logic
(`LLMErrorKind`, `ProviderError.retryable`) that this platform's resilience
story depends on being explicit and testable.

**Tradeoffs.** Two more provider implementations to maintain if a new
model vendor is added — acceptable; adding a provider is "implement one
class," not "touch every call site."

**Consequences.** `MockProvider` isn't a test double bolted on afterward —
it's a first-class provider whose deterministic, seeded behavior (per
model, hallucination-tendency-driven) is what makes the entire demo and
test suite reproducible.

## 5. Deterministic metrics *and* an LLM judge, not either/or

**Context.** The spec is explicit: don't rely entirely on an LLM-as-judge
(section 5).

**Decision.** Seven deterministic evaluators (embedding-similarity- or
arithmetic-based) run on every trace; the judge is one more evaluator among
them, contributing 35% of `overall_quality`, with a deterministic fallback
if it never returns valid structured output.

**Alternatives.** Judge-only (fast to build, but nondeterministic,
costly at scale, and a single point of failure for the whole evaluation
pipeline — see the malformed-JSON retry path this decision forces you to
build anyway); deterministic-only (cheap and fast, but blind to nuance a
judge catches, like "technically on-topic but unhelpful").

**Tradeoffs.** Two evaluation philosophies to keep aligned — the
`_QUALITY_WEIGHTS` blend in
[`evaluation/pipeline.py`](../src/sentinellm/evaluation/pipeline.py) is a
tuned choice, not a law of nature, and is called out as such.

**Consequences.** The pipeline degrades gracefully: judge outage or
malformed output never blocks the deterministic metrics, and
`overall_quality` still gets computed (just without the judge's
contribution).

## 6. Semantic cache: cosine similarity now, ANN index later

**Context.** Semantic caching needs a similarity search over recent
queries; building a production ANN index is out of proportion to this
project's demo-scale traffic.

**Decision.** `SemanticCache` scans the most recent 200 entries for a
(application, model) pair and computes cosine similarity in Python
([`caching/semantic_cache.py`](../src/sentinellm/caching/semantic_cache.py)).

**Alternatives.** pgvector with an IVFFlat/HNSW index; a dedicated vector
DB.

**Tradeoffs.** O(n) per lookup — the benchmark suite measures this
explicitly (~110 lookups/sec against 200 entries, see
[docs/performance.md](performance.md)) and it is the one number in this
repo that is deliberately *not* production-scale, on purpose, with the
upgrade path written down rather than pretended away.

**Consequences.** The `SemanticCache` interface (`lookup`/`store`) doesn't
change when the backing search does — only `_find_candidates` would.

## 7. OpenTelemetry for tracing, Prometheus for metrics

**Context.** The spec wants both distributed tracing and time-series
metrics; conflating them into one system usually serves neither well.

**Decision.** OpenTelemetry's tracer API for spans (console exporter
locally, OTLP when configured), `prometheus-client` for counters/
histograms scraped at `/metrics`.

**Alternatives.** A single vendor APM SDK (Datadog, New Relic) — rejected
for a portfolio project: it would make the observability story
non-reproducible without a paid account.

**Tradeoffs.** Two libraries instead of one; both are industry-standard
and vendor-neutral, so this is a small tax for real portability.

**Consequences.** Any OTLP-compatible backend (Jaeger, Tempo, Honeycomb)
works without code changes; any Prometheus-compatible scraper works the
same way.

## 8. The router excludes before it scores

**Context.** A pure weighted-sum routing formula can still pick a weak
model for a complex task if its cost/latency advantage outweighs a modest
quality deficit in the formula — that's a *soft* preference, and the spec's
demo scenario (complex → strong model, high-risk → high-quality model)
needs a *guarantee*.

**Decision.** Before scoring, candidates are filtered: provider-`down`
candidates are excluded outright; candidates below a task-dependent quality
floor (raised for `complex` classification or `risk >= 0.8`) are excluded
before the weighted score ever runs.

**Alternatives.** Weights alone, tuned so the guarantee "usually" holds —
rejected as fragile and impossible to reason about from the constant
weights alone (see the min-max-normalization discussion in
[docs/routing.md](routing.md) for why raw weight-tuning was insufficient
on its own).

**Tradeoffs.** Two mechanisms (a hard floor and a soft score) to explain
instead of one — worth it because "why was this model excluded" is a
distinct, equally important question from "why did this model win," and
the API surfaces both (`excluded_reason` vs. `routing_score`).

**Consequences.** A request can have zero eligible candidates (all
excluded) — `NoHealthyCandidateError` is a first-class, tested outcome, not
an edge case discovered in production.

## 9. API versioning from day one (`/api/v1/...`)

**Context.** Trace/evaluation schemas will evolve; existing SDK
integrations must not break silently.

**Decision.** Every route is prefixed `/api/v1/`, and the version is part
of the URL, not a header.

**Alternatives.** Header-based versioning (`Accept: application/vnd.
sentinel.v1+json`) — more RESTfully "pure," but far less discoverable in
`/docs`, curl examples, and browser navigation; unversioned (reject —
breaking every integrator's SDK on every backend deploy is not acceptable
for a platform other services depend on).

**Tradeoffs.** URL versioning is visible in every route definition; a v2
would mean parallel route modules for whatever changed, not just a new
serializer branch.

**Consequences.** The SDK and dashboard both hardcode `/api/v1`, so a
hypothetical v2 is additive, not a breaking migration for existing
callers.

## 10. Idempotent ingestion and idempotent evaluation, at two different layers

**Context.** A retrying client (network blip, at-least-once delivery from
the job queue) must not create duplicate traces or duplicate evaluations.

**Decision.** Two separate idempotency mechanisms at two separate layers:
`traces.trace_id` has a unique constraint, and `POST /traces` checks for an
existing row before inserting (returns the original, doesn't error); the
worker claims a trace with `UPDATE traces SET evaluation_status =
'evaluating' WHERE evaluation_status = 'pending'` and checks the claim's
row count before doing any evaluation work, and `evaluations.trace_id` also
carries a unique constraint as a second line of defense.

**Alternatives.** A single idempotency key checked once at the API edge —
insufficient, because it doesn't protect against the *worker* processing
the same queue message twice (Redis `BRPOP` is at-least-once, not
exactly-once).

**Tradeoffs.** Two idempotency checks to maintain instead of one, because
they guard two different failure modes (duplicate client submission vs.
duplicate queue delivery).

**Consequences.** `tests/api/test_traces_api.py::test_duplicate_trace_
ingestion_is_idempotent` and `tests/integration/test_worker_evaluate.py::
test_duplicate_delivery_of_same_job_is_a_no_op` test these independently,
because they are independent guarantees.

## 11. A modular monolith, not eight physical microservices

**Context.** The spec's architecture section names eight services
(sentinel-api, -ingestion, -worker, -evaluator, -router, -retrieval,
-monitor, -dashboard). Building eight separately deployable, separately
versioned services for a project meant to run on one developer's laptop
would be the overengineering the spec's own quality bar (section 36)
explicitly warns against.

**Decision.** One installable Python distribution (`sentinellm`) with
domain-oriented modules (`llm/`, `evaluation/`, `routing/`, `retrieval/`,
`caching/`, `pricing/`), two deployable *processes* (`api`, `worker`), and
one frontend. The eight-service names in the spec map to modules/processes
in the table in the [README](../README.md#architecture), not to eight
container images.

**Alternatives.** Eight literal services with their own repos/Dockerfiles/
CI pipelines and an API gateway — the "textbook" microservices answer, and
the wrong one at this scale: it would add network hops, serialization
overhead, and distributed-transaction complexity to what is fundamentally
a small number of write paths (ingest → evaluate) with no genuinely
independent scaling or ownership boundaries yet.

**Tradeoffs.** The API and evaluation logic currently share a deploy unit,
so a bug in one can (in principle) affect the other's process — mitigated
by the API and worker being *separate processes* even though they share a
codebase, so a worker crash doesn't take the API down.

**Consequences.** If `sentinel-evaluator` genuinely needed independent
scaling/ownership (e.g. a different team, a GPU-bound custom evaluator),
splitting `sentinellm.evaluation` into its own service is a matter of
extracting a module that already has a clean interface (`EvaluationPipeline`)
— not a rewrite.
