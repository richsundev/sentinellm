# Architecture

## Layout

```
src/sentinellm/
  core/            settings, structured logging, ids, the Redis job queue
  db/              SQLAlchemy models, session factory, Alembic migrations
  llm/             LLMProvider ABC + Mock/OpenAI/Anthropic + resilient fallback client
  embeddings/      EmbeddingProvider ABC + Mock (feature-hashing) + sentence-transformers
  evaluation/      deterministic evaluators, LLM judge, hallucination detection, RAG metrics, pipeline
  routing/         complexity/risk classification, the router, per-model stats
  retrieval/       in-memory embedding retriever + reranker
  caching/         semantic response cache
  pricing/         model catalog + cost calculator
  observability/   Prometheus metrics, OpenTelemetry tracing
  api/             FastAPI app, routers, Pydantic schemas, auth, rate limiting
  services/        cross-cutting orchestration (the /generate pipeline, evaluation-pipeline factory)
  worker/          queue consumer + evaluation/regression/alerting tasks
  sdk/             the client SDK integrating applications use
frontend/          Next.js dashboard
infrastructure/    Docker, Kubernetes, Prometheus config
datasets/          the benchmark Q&A dataset
scripts/           seed_demo.py, run_benchmarks.py
tests/             unit / integration / api
```

Why modules are organized by *domain* (`evaluation/`, `routing/`,
`caching/`) rather than purely by technical layer: a reviewer asking "how
does hallucination detection work" should find one directory, not grep
across `models/`, `services/`, `handlers/` for every layer that touches it.

## Request lifecycle: `POST /api/v1/generate`

This is the platform's most important code path — it's what
`scripts/seed_demo.py` calls to produce every trace in the demo, and it's
where routing, caching, and resilient fallback all compose
([`services/generation.py`](../src/sentinellm/services/generation.py)):

1. **Retrieval** (if `dataset_id` given): embed the question, cosine-rank
   the dataset's records, keep `top_k`.
2. **Reranking**: a lexical-overlap rescoring pass (`ScoreJitterReranker`)
   — a stand-in for a cross-encoder, see
   [`retrieval/reranker.py`](../src/sentinellm/retrieval/reranker.py).
3. **Routing** (unless `preferred_model` is given): classify task
   complexity + risk, load all non-`down` non-judge models from the
   pricing catalog, score them, persist the full decision.
4. **Semantic cache lookup**: embed the question, scan recent cache
   entries for the (application, model) pair, return on a similarity hit.
5. **Prompt construction**: build the system/user message pair.
6. **Resilient LLM generation**: try the routed model, then each
   fallback candidate in ranked order, with bounded retries + exponential
   backoff per model (see [`llm/resilient.py`](../src/sentinellm/llm/resilient.py)).
7. **Cost calculation**: token counts × the model's DB-stored (or catalog
   fallback) per-1K pricing.
8. **Persistence**: one `Trace` row, its `TraceSpan` children (one per
   stage above, each with a real measured `start_ms`/`duration_ms`), and a
   `RoutingDecision` row if routing ran.
9. **Evaluation enqueue**: pushes the trace's DB id onto the Redis queue;
   the worker picks it up asynchronously (see
   [docs/evaluation.md](evaluation.md)).

`POST /api/v1/traces` is the other ingestion path — for applications that
already ran their own LLM call and just want to report it. It skips steps
1–7 and goes straight to persistence + enqueue, and is idempotent on
`trace_id` (see [design decision 10](design-decisions.md#10-idempotent-ingestion-and-idempotent-evaluation-at-two-different-layers)).

## Database

16 tables. The ones worth calling out:

- **`traces`** is the hub: FK targets from `trace_spans`, `evaluations`,
  `routing_decisions`. `evaluation_status` (`pending → evaluating →
  completed | failed | skipped`) drives the worker's claim query.
- **`evaluations`** has `trace_id UNIQUE` — the idempotency guarantee
  described in design decision 10. `overall_quality` and
  `hallucination_score` are denormalized onto this row (not recomputed
  from `evaluation_metrics`/`hallucination_claims` on every read) because
  they're read on nearly every dashboard query.
- **`evaluation_metrics`** and **`hallucination_claims`** are 1:N children
  of `evaluations` — one row per evaluator, one row per extracted claim.
- **`prompt_versions`** is unique on `(prompt_id, version)`; versions are
  monotonically assigned server-side (`POST /prompts` computes `max(version)
  + 1`), never client-supplied, so two concurrent version creations can't
  collide on the same number.
- **`models`** (the pricing catalog table) doubles as the router's
  candidate source and the `/models` dashboard's data source — one table,
  two consumers, no duplication.
- **`semantic_cache_entries`** stores the embedding as a JSON array of
  floats (see [design decision 6](design-decisions.md#6-semantic-cache-cosine-similarity-now-ann-index-later)
  for why this isn't pgvector yet).

Indexes: `traces(application_id, created_at)` and `traces(model,
created_at)` back the two most common dashboard queries (per-application
history, per-model routing stats); `traces(trace_id)` (unique) backs
ingestion idempotency lookups; `traces(evaluation_status)` backs the
worker's claim query.

## Why JSON columns instead of Postgres JSONB-specific features

The schema uses SQLAlchemy's generic `JSON` type (renders as `JSON` on
SQLite, `JSON`/`JSONB`-compatible on Postgres) rather than
`postgresql.JSONB` with GIN indexes, and string primary keys instead of
native `UUID`. This is a deliberate portability choice — the full test
suite runs against SQLite with zero setup — documented (not just assumed)
because it's a real tradeoff: production would benefit from JSONB's
indexing on `retrieved_documents`/`candidates` if those columns were ever
queried by content rather than always read as part of their parent row (as
they are today).
