# Observability

## Structured logging

[`core/logging.py`](../src/sentinellm/core/logging.py) configures
`structlog` to emit JSON lines with an ISO timestamp, log level, and —
via a custom processor reading from `contextvars` — a `request_id` (set by
`CorrelationAndMetricsMiddleware` on every HTTP request, from the incoming
`X-Request-ID` header if present, generated otherwise) and `trace_id`
where applicable. Every log line is therefore greppable/filterable by
request or trace without any string parsing, and the `X-Request-ID` is
echoed back in the response header so a client can correlate its own logs
with the server's.

## Prometheus metrics

Exposed at `GET /metrics` ([`observability/metrics.py`](../src/sentinellm/observability/metrics.py)):

| Metric | Type | Labels |
|---|---|---|
| `sentinel_requests_total` | Counter | method, path, status |
| `sentinel_request_latency_seconds` | Histogram | method, path |
| `sentinel_llm_requests_total` | Counter | model, provider, status |
| `sentinel_llm_errors_total` | Counter | model, provider, kind |
| `sentinel_llm_cost_total` | Counter | model, application_id |
| `sentinel_evaluation_score` | Histogram | metric_name |
| `sentinel_cache_hits_total` | Counter | result (hit/miss) |
| `sentinel_routing_decisions_total` | Counter | selected_model, task_complexity |

`sentinel_request_latency_seconds` and `sentinel_requests_total` are
recorded by `CorrelationAndMetricsMiddleware` for *every* request
automatically; the rest are recorded at the point of the relevant domain
event (a routing decision, an LLM call, a cache lookup) so they reflect
what actually happened, not an inferred proxy.

### Worker metrics

The worker is a separate process, so the API's `/metrics` cannot see anything
recorded in it — it serves its own on `SENTINEL_WORKER_METRICS_PORT`
(default `9100`; `0` disables). That is where `sentinel_evaluation_score` is
actually recorded, alongside:

| Metric | Type | Labels |
|---|---|---|
| `sentinel_worker_loop_runs_total` | Counter | loop, outcome (`ok` / `error` / `skipped`) |
| `sentinel_worker_loop_duration_seconds` | Histogram | loop |
| `sentinel_worker_loop_last_success_timestamp_seconds` | Gauge | loop |
| `sentinel_queue_depth` | Gauge | — |
| `sentinel_rollout_decisions_total` | Counter | decision (`advance` / `promote` / `rollback`) |
| `sentinel_alerts_fired_total` | Counter | rule, severity |
| `sentinel_model_status_changes_total` | Counter | model, status |

`loop` is one of `regression`, `alerting`, `model_health`, `rollout`,
`queue_depth`. `skipped` means another replica held that loop's advisory lock
for the pass (see [decision 12](design-decisions.md#12-periodic-worker-loops-are-cluster-wide-singletons-postgres-advisory-locks)),
so with several replicas a healthy loop shows a mix of `ok` and `skipped`.
A loop is stalled when `time() - max by (loop)
(sentinel_worker_loop_last_success_timestamp_seconds)` grows past a few
intervals — a failure that is otherwise only visible as an absence in logs.
`sentinel_queue_depth` is the metric the worker HPA is meant to scale on
(Prometheus + prometheus-adapter, see the
[Kubernetes README](../infrastructure/kubernetes/README.md)).

## Prometheus + Grafana

```bash
docker compose --profile monitoring up      # add -d, and --scale worker=2 to see the lock work
```

Starts Prometheus on <http://localhost:9090> and Grafana on
<http://localhost:3001> (anonymous read-only; admin login `admin`/`admin`) in
addition to the normal stack. Everything is provisioned from files:

* [`prometheus.yml`](../infrastructure/monitoring/prometheus.yml) scrapes the
  API and — via DNS service discovery, so every replica of a scaled worker is
  found — the worker.
* [`grafana/dashboards/sentinellm.json`](../infrastructure/monitoring/grafana/dashboards/sentinellm.json)
  opens as Grafana's home dashboard: API traffic and latency, LLM calls /
  errors / spend / routing, evaluation scores and queue depth, and an
  "Autonomous loops" row (loop staleness, passes by outcome, pass duration,
  rollout decisions, alerts fired, model status changes).
* [`alert_rules.yml`](../infrastructure/monitoring/alert_rules.yml) has the
  request-level SLO rules plus a `sentinellm.autonomy` group: API/worker
  down, a stalled or failing loop, evaluation backlog, an automatic rollout
  rollback, a model automatically flagged down. A stalled loop can't alert
  about its own stall, which is why these live outside the application's
  DB-backed alerting.

## Distributed tracing

[`observability/tracing.py`](../src/sentinellm/observability/tracing.py)
configures an OpenTelemetry `TracerProvider`. Tracing is **off unless
`SENTINEL_OTEL_EXPORTER_OTLP_ENDPOINT` is set**; then the API and the worker
export to that OTLP collector (Jaeger, Tempo, Honeycomb, a vendor APM) with
no code change. The API is auto-instrumented (one span per HTTP request), and
`sentinel.generate` and `sentinel.evaluate` spans wrap the generation and
evaluation-job paths. Unset, the tracer is a no-op: nothing is exported or
printed, and the spans in the code cost nothing.

This is a different (and complementary) tracing concept from the
application-level `TraceSpan` rows stored per LLM trace (retrieval →
reranking → routing → generation → evaluation, rendered as the timeline on
`/trace/[id]`): those are *product* spans, persisted and queryable
alongside the request they belong to; OpenTelemetry spans are
*infrastructure* traces for debugging the platform's own request handling.
Both exist because they answer different questions — "why was this
specific LLM answer slow" vs. "why is the API p99 elevated across all
traffic."

## Correlation in practice

Every API response carries `X-Request-ID`. Every trace has its own
`trace_id`. A support/debugging workflow: take the `X-Request-ID` from a
slow request, `grep` the API's JSON logs for it to see every log line from
that request's handling, cross-reference with the OTLP trace (if a
collector is configured) for span-level timing, and — if the request
created or touched a `Trace` row — look up `/trace/{trace_id}` for the
product-level breakdown.
