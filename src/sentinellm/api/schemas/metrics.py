from __future__ import annotations

from pydantic import BaseModel


class ModelUsage(BaseModel):
    model: str
    count: int


class ProviderReliability(BaseModel):
    provider: str
    success_rate: float


class TimeseriesPoint(BaseModel):
    timestamp: str
    volume: int
    p95_latency_ms: float
    cost: float


class OverviewMetricsOut(BaseModel):
    request_volume: int
    error_rate: float
    p50_latency_ms: float
    p95_latency_ms: float
    p99_latency_ms: float
    avg_cost_per_request: float
    avg_tokens_per_request: float
    hallucination_rate: float
    avg_faithfulness: float
    avg_relevance: float
    model_usage: list[ModelUsage]
    provider_reliability: list[ProviderReliability]
    timeseries: list[TimeseriesPoint]
    human_feedback_count: int
    human_judge_agreement_rate: float | None


class DailyCost(BaseModel):
    date: str
    cost: float


class ModelCost(BaseModel):
    model: str
    cost: float


class ApplicationCost(BaseModel):
    application_id: str
    cost: float


class CostSummaryOut(BaseModel):
    total_cost: float
    daily: list[DailyCost]
    by_model: list[ModelCost]
    by_application: list[ApplicationCost]
    insight_text: str | None
