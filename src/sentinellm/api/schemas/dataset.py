from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from sentinellm.api.schemas.common import NulStrippingModel


class DatasetRecordIn(NulStrippingModel):
    question: str
    context: str = ""
    expected_answer: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class DatasetCreate(NulStrippingModel):
    name: str = Field(min_length=1, max_length=200)
    version: str = Field(min_length=1, max_length=50)
    description: str | None = None
    records: list[DatasetRecordIn] = Field(default_factory=list)


class DatasetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    version: str
    description: str | None
    record_count: int = 0
    created_at: datetime


class DatasetRecordOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    question: str
    context: str
    expected_answer: str
    metadata: dict[str, Any] = Field(validation_alias="record_metadata", default_factory=dict)
