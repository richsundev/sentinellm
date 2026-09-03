from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ModelStatus = Literal["healthy", "degraded", "down"]


class ModelOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    provider: str
    input_price_per_1k: float
    output_price_per_1k: float
    context_window: int
    avg_quality: float | None = None
    avg_latency_ms: float | None = None
    status: str


class ModelCreate(BaseModel):
    id: str = Field(description="'provider:name', e.g. 'openai:gpt-4o-mini'")
    name: str
    provider: str
    input_price_per_1k: float = Field(ge=0)
    output_price_per_1k: float = Field(ge=0)
    context_window: int = Field(default=8192, gt=0)
    quality_tier: float = Field(
        default=0.5, ge=0.0, le=1.0, description="Router prior until real trace history exists"
    )
    avg_latency_ms_prior: float = Field(default=800.0, gt=0)
    status: ModelStatus = "healthy"


class ModelUpdate(BaseModel):
    name: str | None = None
    input_price_per_1k: float | None = Field(default=None, ge=0)
    output_price_per_1k: float | None = Field(default=None, ge=0)
    context_window: int | None = Field(default=None, gt=0)
    quality_tier: float | None = Field(default=None, ge=0.0, le=1.0)
    avg_latency_ms_prior: float | None = Field(default=None, gt=0)
    status: ModelStatus | None = None
