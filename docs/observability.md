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

See [`infrastructure/monitoring/prometheus.yml`](../infrastructure/monitoring/prometheus.yml)
for a ready-to-use scrape config and
[`alert_rules.yml`](../infrastructure/monitoring/alert_rules.yml) for
example Alertmanager rules built on these exact metric names.

## Distributed tracing

[`observability/tracing.py`](../src/sentinellm/observability/tracing.py)
configures an OpenTelemetry `TracerProvider`. Locally it exports spans to
the console (zero setup); set `SENTINEL_OTEL_EXPORTER_OTLP_ENDPOINT` to
export to any OTLP-compatible collector (Jaeger, Tempo, Honeycomb, a
vendor APM) with no code change.

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
