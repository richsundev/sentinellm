"""Prometheus metric definitions. Scraped at `/metrics` on the API service.

Naming follows the `sentinel_<domain>_<unit>_total|seconds` Prometheus
convention so these compose cleanly with any standard Grafana/Alertmanager
setup.
"""

from __future__ import annotations

from prometheus_client import Counter, Histogram

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
