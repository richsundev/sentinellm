# Performance

## Methodology

`make bench` runs [`scripts/run_benchmarks.py`](../scripts/run_benchmarks.py)
against a real, temporary, file-backed SQLite database (not `:memory:`, so
disk I/O is included) and the platform's real code — nothing here is an
invented number. Each benchmark warms up for 10% of the configured
iteration count (discarded), then times the remaining iterations
sequentially in a single process/single DB connection, reporting
throughput (ops/sec) and p50/p95/p99 latency.

Single-process/single-connection is a deliberate scope: this measures the
*cost of the code path itself* (how expensive is one evaluation pipeline
run, one routing decision, one cache lookup), not the throughput ceiling
of a scaled-out deployment with a connection pool and multiple worker
replicas. Extrapolating "ops/sec × replica count" would overstate real
achievable throughput (DB connection contention, GIL-bound CPU work in the
evaluator/router don't scale linearly) and is not claimed here.

## Results (200 iterations, reproduce with `make bench`)

| Benchmark | Throughput | p50 | p95 | p99 |
|---|---:|---:|---:|---:|
| Trace ingestion (DB insert, trace + 1 span) | ~1,015/s | 0.97ms | 1.21ms | 1.32ms |
| Evaluation pipeline (8 deterministic + hallucination + judge) | ~4,497/s | 0.21ms | 0.29ms | 0.40ms |
| Router decision (4 candidates) | ~64,956/s | 0.015ms | 0.018ms | 0.036ms |
| Semantic cache lookup (200-entry linear scan) | ~110/s | 8.7ms | 10.5ms | 26.3ms |
| DB query (filtered trace list, limit 25) | ~1,297/s | 0.73ms | 1.14ms | 1.85ms |
| Dataset retrieval (`/generate` + `dataset_id`, top-3 over 200 records) | ~650–775/s | 1.3–1.5ms | 1.6–2.1ms | 1.8–2.5ms |

## Reading these numbers

- **Dataset retrieval was ~9.5ms and is ~1.3ms** (measured before/after on the
  same machine, mock embeddings). `/generate` with a `dataset_id` used to load
  every record and re-embed the whole corpus on every request; the corpus is now
  indexed once ([`retrieval/corpus_cache.py`](../src/sentinellm/retrieval/corpus_cache.py):
  documents plus unit-length vectors, LRU-bounded, keyed by dataset and record
  count) and a comparison is a dot product. With the mock's hash embeddings the
  saving is modest; with a real embedding model it is the difference between one
  model call per request and hundreds — that cost is now paid once per dataset.

- **The router is essentially free** (microseconds) — it's pure Python
  arithmetic over a handful of candidates, no I/O. This is expected and
  intentional: routing decisions happen on the hot path of every
  `/generate` call and must not become the bottleneck.
- **The evaluation pipeline is fast** (~4,500/s, sub-millisecond) *because*
  every deterministic evaluator is a pure function over already-computed
  embeddings, and the benchmark uses `TimingMockProvider` (skips the
  judge's simulated network latency) specifically to isolate the
  pipeline's own overhead from provider latency, which in a real deployment
  would dominate (a real judge-model API call is 200ms–2s, not 0.2ms).
- **The semantic cache lookup is the one number here that is *not*
  production-scale, on purpose.** At ~110 lookups/sec against just 200
  cached entries, this will not hold up under real cache population sizes
  — it's an O(n) linear scan (see
  [design decision 6](design-decisions.md#6-semantic-cache-cosine-similarity-now-ann-index-later)).
  The fix is a known, named one: move `_find_candidates` in
  [`caching/semantic_cache.py`](../src/sentinellm/caching/semantic_cache.py)
  to a pgvector IVFFlat/HNSW index (or a dedicated vector store) — the
  `SemanticCache.lookup`/`store` interface doesn't need to change.
- **Trace ingestion and DB queries are dominated by SQLite's fsync
  behavior** in this benchmark; PostgreSQL with connection pooling
  (`asyncpg`) in the real deployment path has different — likely better
  under concurrent load — characteristics, not reproduced here since the
  test suite intentionally runs against SQLite for zero-setup
  reproducibility (see [design decision 1](design-decisions.md#1-postgresql-as-the-primary-datastore)).

## What would change these numbers in a real deployment

- A real LLM provider call replaces the ~0ms `TimingMockProvider`/
  `MockProvider` latency with real network latency (hundreds of ms to
  several seconds) — this dominates end-to-end request time in production,
  which is exactly why evaluation is asynchronous (see [design decision
  3](design-decisions.md#3-asynchronous-evaluation-always)) and why the
  resilient client's retry/fallback behavior
  ([docs/routing.md](routing.md#fallback--resilience)) matters more than
  the evaluation pipeline's own (already-fast) overhead.
- Multiple worker replicas process the evaluation queue in parallel —
  throughput scales with replica count up to the point Postgres connection
  pooling or Redis becomes the bottleneck (not yet measured; a natural
  follow-up load test).
- The semantic cache's linear scan gets meaningfully worse as cache
  population grows past a few hundred entries per (application, model)
  pair — this is the one part of the current design that should not be
  trusted past demo scale without the pgvector migration above.
