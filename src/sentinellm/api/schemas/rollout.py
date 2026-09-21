from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from sentinellm.api.schemas.common import NulStrippingModel

RolloutStage = Literal["running", "paused", "promoted", "rolled_back"]


class RolloutCreate(NulStrippingModel):
    application_id: str = Field(min_length=1, max_length=200)
    incumbent_model: str = Field(min_length=1, max_length=100)
    challenger_model: str = Field(min_length=1, max_length=100)
    initial_pct: float = Field(default=10.0, ge=0, le=100)
    quality_floor: float = Field(default=0.7, ge=0, le=1)
    max_quality_regression: float = Field(
        default=0.1,
        ge=0,
        le=1,
        description=(
            "How far below the incumbent's own average quality (measured over the same "
            "window) the challenger may fall before it is rolled back"
        ),
    )
    max_error_rate: float = Field(default=0.1, ge=0, le=1)
    min_sample_size: int = Field(default=10, ge=1, le=1_000_000)
    step_pct: float = Field(default=10.0, gt=0, le=100)
    max_pct: float = Field(default=100.0, gt=0, le=100)

    @model_validator(mode="after")
    def _consistent(self) -> RolloutCreate:
        if self.incumbent_model == self.challenger_model:
            raise ValueError("incumbent_model and challenger_model must differ")
        if self.initial_pct > self.max_pct:
            raise ValueError("initial_pct cannot exceed max_pct")
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
    max_quality_regression: float
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
