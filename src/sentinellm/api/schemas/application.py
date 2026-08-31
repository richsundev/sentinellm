from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict


class ApplicationCreate(BaseModel):
    name: str
    description: str | None = None


class ApplicationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    description: str | None
    created_at: datetime


class APIKeyCreate(BaseModel):
    application_id: str
    name: str = "default"
    role: Literal["read", "write", "admin"] = "write"


class APIKeyCreated(BaseModel):
    id: str
    name: str
    role: str
    key_prefix: str
    plaintext_key: str


class APIKeyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    application_id: str
    name: str
    role: str
    key_prefix: str
    revoked: bool
    created_at: datetime
    last_used_at: datetime | None
