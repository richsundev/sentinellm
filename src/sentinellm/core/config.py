"""Central application configuration, sourced entirely from environment variables.

Every tunable in the platform (router weights, alert thresholds, cache behavior)
lives here rather than scattered as magic numbers through the codebase, so an
operator can retune production behavior without a code change or redeploy of
application logic — only a config/env change.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SENTINEL_", env_file=".env", extra="ignore")

    env: Literal["local", "test", "staging", "production"] = "local"
    log_level: str = "INFO"
    secret_key: str = "change-me-in-production"

    database_url: str = "postgresql+psycopg://sentinel:sentinel@localhost:5432/sentinellm"
    redis_url: str = "redis://localhost:6379/0"

    llm_provider: Literal["mock", "openai", "anthropic"] = "mock"
    embedding_provider: Literal["mock", "sentence-transformers"] = "mock"

    cache_enabled: bool = True
    cache_similarity_threshold: float = 0.95

    pii_redaction_enabled: bool = False

    router_quality_weight: float = 0.35
    router_cost_weight: float = 0.35
    router_latency_weight: float = 0.15
    router_risk_weight: float = 0.15

    regression_threshold_pct: float = 5.0

    alert_webhook_url: str | None = None
    alert_webhook_format: Literal["generic", "slack"] = "generic"
    hallucination_rate_threshold: float = 0.08
    p95_latency_threshold_ms: float = 3000.0
    error_rate_threshold: float = 0.05
    quality_score_threshold: float = 0.85
    daily_cost_budget: float = 50.0

    api_host: str = "0.0.0.0"
    api_port: int = 8000
    rate_limit_per_minute: int = 120

    # Worker process: the API's `/metrics` can't see anything recorded in the
    # worker (evaluation scores, loop health, queue depth), so the worker
    # serves its own. 0 disables it.
    worker_metrics_port: int = 9100
    # Cadence of the regression / alerting / model-health / rollout loops.
    worker_interval_seconds: float = 60.0

    demo_api_key: str = "demo-api-key"

    otel_exporter_otlp_endpoint: str | None = None

    @model_validator(mode="after")
    def _check_router_weights(self) -> Settings:
        total = (
            self.router_quality_weight
            + self.router_cost_weight
            + self.router_latency_weight
            + self.router_risk_weight
        )
        if not (0.98 <= total <= 1.02):
            raise ValueError(f"Router weights must sum to ~1.0, got {total}")
        return self

    @property
    def is_test(self) -> bool:
        return self.env == "test"


@lru_cache
def get_settings() -> Settings:
    return Settings()
