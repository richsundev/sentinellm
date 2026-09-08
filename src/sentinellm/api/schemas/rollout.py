from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

RolloutStage = Literal["running", "paused", "promoted", "rolled_back"]


class RolloutCreate(BaseModel):
    application_id: str
    incumbent_model: str
    challenger_model: str
    initial_pct: float = Field(default=10.0, ge=0, le=100)
    quality_floor: float = Field(default=0.7, ge=0, le=1)
    max_error_rate: float = Field(default=0.1, ge=0, le=1)
    min_sample_size: int = Field(default=10, ge=1)
    step_pct: float = Field(default=10.0, gt=0, le=100)
    max_pct: float = Field(default=100.0, gt=0, le=100)

    @model_validator(mode="after")
    def _distinct_models(self) -> RolloutCreate:
        if self.incumbent_model == self.challenger_model:
            raise ValueError("incumbent_model and challenger_model must differ")
        return self


class RolloutOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    application_id: str
    incumbent_model: str
    challenger_model: str
    traffic_pct: float
    stage: RolloutStage
    quality_floor: float
    max_error_rate: float
    min_sample_size: int
    step_pct: float
    max_pct: float
    last_evaluated_at: datetime | None
    outcome_reason: str | None
    created_at: datetime


class RolloutArmStats(BaseModel):
    model: str
    request_count: int
    error_rate: float
    avg_quality: float | None
    avg_latency_ms: float
    avg_cost: float


class RolloutDetailOut(RolloutOut):
    incumbent_stats: RolloutArmStats
    challenger_stats: RolloutArmStats
