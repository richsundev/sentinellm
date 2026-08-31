from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

PromptStatus = Literal["draft", "testing", "production", "deprecated"]


class PromptVersionCreate(BaseModel):
    prompt_id: str
    template: str
    variables: list[str] = Field(default_factory=list)
    status: PromptStatus = "draft"
    author: str = "unknown"
    metadata: dict[str, Any] = Field(default_factory=dict)


class PromptStatusUpdate(BaseModel):
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
