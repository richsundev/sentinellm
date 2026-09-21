"""Prometheus metric definitions. Scraped at `/metrics` on the API service.

Naming follows the `sentinel_<domain>_<unit>_total|seconds` Prometheus
convention so these compose cleanly with any standard Grafana/Alertmanager
setup.
"""

from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram

REQUESTS_TOTAL = Counter(
    "sentinel_requests_total",
    "Total HTTP requests handled by the API",
    ["method", "path", "status"],
)
REQUEST_LATENCY_SECONDS = Histogram(
    "sentinel_request_latency_seconds", "HTTP request latency", ["method", "path"]
)
LLM_REQUESTS_TOTAL = Counter(
    "sentinel_llm_requests_total", "Total LLM provider calls", ["model", "provider", "status"]
)
LLM_ERRORS_TOTAL = Counter(
    "sentinel_llm_errors_total", "Total LLM provider call failures", ["model", "provider", "kind"]
)
LLM_COST_TOTAL = Counter(
    "sentinel_llm_cost_total", "Cumulative estimated LLM spend in USD", ["model", "application_id"]
)
EVALUATION_SCORE = Histogram(
    "sentinel_evaluation_score",
    "Distribution of evaluation metric scores",
    ["metric_name"],
    buckets=(0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0),
)
CACHE_HITS_TOTAL = Counter(
    "sentinel_cache_hits_total",
    "Semantic cache lookups",
    ["result"],  # result: hit | miss
)
ROUTING_DECISIONS_TOTAL = Counter(
    "sentinel_routing_decisions_total",
    "Router model selections",
    ["selected_model", "task_complexity"],
)

# --- Worker process ---------------------------------------------------------
# Recorded by the worker, which serves them on its own port
# (`SENTINEL_WORKER_METRICS_PORT`) — the API's `/metrics` never sees these.
WORKER_LOOP_RUNS_TOTAL = Counter(
    "sentinel_worker_loop_runs_total",
    "Periodic worker loop passes",
    ["loop", "outcome"],  # outcome: ok | error | skipped (another replica held the lock)
)
WORKER_LOOP_LAST_SUCCESS_TIMESTAMP = Gauge(
    "sentinel_worker_loop_last_success_timestamp_seconds",
    "Unix time this replica last completed a pass of the loop successfully",
    ["loop"],
)
WORKER_LOOP_DURATION_SECONDS = Histogram(
    "sentinel_worker_loop_duration_seconds",
    "Wall-clock duration of a periodic worker loop pass",
    ["loop"],
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60),
)
QUEUE_DEPTH = Gauge("sentinel_queue_depth", "Pending jobs in the evaluation queue")

# --- Autonomous decisions ---------------------------------------------------
ROLLOUT_DECISIONS_TOTAL = Counter(
    "sentinel_rollout_decisions_total",
    "Automatic canary rollout decisions",
    ["decision"],  # advance | promote | rollback
)
ALERTS_FIRED_TOTAL = Counter(
    "sentinel_alerts_fired_total", "Alerts fired by the worker", ["rule", "severity"]
)
MODEL_STATUS_CHANGES_TOTAL = Counter(
    "sentinel_model_status_changes_total",
    "Automatic model health status transitions",
    ["model", "status"],
)
