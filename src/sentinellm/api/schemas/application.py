from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from sentinellm.api.schemas.common import NulStrippingModel


class ApplicationCreate(NulStrippingModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None
    daily_cost_budget: float | None = Field(default=None, ge=0)


class ApplicationUpdate(NulStrippingModel):
    description: str | None = None
    daily_cost_budget: float | None = Field(default=None, ge=0)


class ApplicationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    description: str | None
    daily_cost_budget: float | None
    created_at: datetime


class APIKeyCreate(NulStrippingModel):
    application_id: str = Field(max_length=36)
    name: str = Field(default="default", min_length=1, max_length=200)
    role: Literal["read", "write", "admin"] = "write"
    scoped_to_application: bool = Field(
        default=False,
        description="If true, this key can only see/write its own application's data",
    )


class APIKeyCreated(BaseModel):
    id: str
    name: str
    role: str
    key_prefix: str
    plaintext_key: str
    scoped_to_application: bool


class APIKeyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    application_id: str
    name: str
    role: str
    key_prefix: str
    revoked: bool
    scoped_to_application: bool
    created_at: datetime
    last_used_at: datetime | None
