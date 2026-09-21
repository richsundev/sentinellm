from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from sentinellm.api.schemas.common import NulStrippingModel

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
    status_auto: bool
    status_reason: str | None


class ModelCreate(NulStrippingModel):
    id: str = Field(
        min_length=1, max_length=100, description="'provider:name', e.g. 'openai:gpt-4o-mini'"
    )
    name: str = Field(min_length=1, max_length=100)
    provider: str = Field(min_length=1, max_length=50)
    input_price_per_1k: float = Field(ge=0)
    output_price_per_1k: float = Field(ge=0)
    context_window: int = Field(default=8192, gt=0, le=2_147_483_647)
    quality_tier: float = Field(
        default=0.5, ge=0.0, le=1.0, description="Router prior until real trace history exists"
    )
    avg_latency_ms_prior: float = Field(default=800.0, gt=0)
    status: ModelStatus = "healthy"


class ModelUpdate(NulStrippingModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    input_price_per_1k: float | None = Field(default=None, ge=0)
    output_price_per_1k: float | None = Field(default=None, ge=0)
    context_window: int | None = Field(default=None, gt=0, le=2_147_483_647)
    quality_tier: float | None = Field(default=None, ge=0.0, le=1.0)
    avg_latency_ms_prior: float | None = Field(default=None, gt=0)
    status: ModelStatus | None = None
    status_auto: bool | None = Field(
        default=None,
        description=(
            "Set explicitly to re-enable automatic health management "
            "(a bare `status` PATCH pins it to False, see routers/models.py)."
        ),
    )
