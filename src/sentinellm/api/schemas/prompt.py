from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from sentinellm.api.schemas.common import NulStrippingModel

PromptStatus = Literal["draft", "testing", "production", "deprecated"]


class PromptVersionCreate(NulStrippingModel):
    prompt_id: str = Field(min_length=1, max_length=200)
    template: str = Field(min_length=1, max_length=200_000)
    variables: list[Annotated[str, StringConstraints(max_length=50)]] = Field(
        default_factory=list, max_length=50
    )
    status: PromptStatus = "draft"
    author: str = Field(default="unknown", max_length=200)
    metadata: dict[str, Any] = Field(default_factory=dict)


class PromptStatusUpdate(NulStrippingModel):
    status: PromptStatus


class PromptVersionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    prompt_id: str
    version: int
    template: str
    variables: list[str]
    status: str
    author: str
    created_at: datetime


class PromptPromoteRequest(NulStrippingModel):
    quality_pass_threshold: float = Field(default=0.7, ge=0.0, le=1.0)


class PromptRenderRequest(NulStrippingModel):
    variables: dict[str, str] = Field(default_factory=dict, max_length=50)


class PromptRenderOut(BaseModel):
    prompt_id: str
    version: int
    # None when a placeholder has no value; `missing` says which.
    rendered: str | None
    missing: list[str]


class PromptPromotionOut(BaseModel):
    promoted: PromptVersionOut
    justifying_experiment_id: str
    justifying_experiment_pass_rate: float
    demoted_version: int | None
