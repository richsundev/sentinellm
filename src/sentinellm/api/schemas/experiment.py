from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from sentinellm.api.schemas.common import NulStrippingModel


class ExperimentRunRequest(NulStrippingModel):
    name: str = Field(min_length=1, max_length=200)
    model: str = Field(min_length=1, max_length=100)
    prompt_id: str = Field(min_length=1, max_length=200)
    prompt_version: int = Field(ge=1, le=2_147_483_647)
    dataset_id: str = Field(min_length=1, max_length=36)
    application_id: str = Field(default="experiment-runner", min_length=1, max_length=200)
    sample_size: int | None = Field(default=None, ge=1, le=50)
    quality_pass_threshold: float = Field(default=0.7, ge=0.0, le=1.0)
    parameters: dict[str, Any] = Field(default_factory=dict)


class ExperimentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    model: str
    prompt_id: str
    prompt_version: int
    dataset_id: str
    faithfulness: float
    relevance: float
    hallucination_rate: float
    p95_latency_ms: float
    cost_per_request: float
    pass_rate: float
    git_commit: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class MetricComparison(BaseModel):
    metric_name: str
    value_a: float
    value_b: float
    delta: float
    delta_pct: float | None
    better: str  # "a" | "b" | "tie"


class ExperimentComparisonOut(BaseModel):
    experiment_a: ExperimentOut
    experiment_b: ExperimentOut
    metrics: list[MetricComparison]
