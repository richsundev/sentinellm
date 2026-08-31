from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ExperimentCreate(BaseModel):
    name: str
    model: str
    prompt_id: str
    prompt_version: int
    dataset_id: str
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
    created_at: datetime
