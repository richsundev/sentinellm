from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from sentinellm.api.schemas.common import NulStrippingModel

BudgetAction = Literal["alert", "downgrade", "block"]
_BUDGET_ACTION_HELP = (
    "What `/generate` does once the trailing-24h spend passes daily_cost_budget: 'alert' (the "
    "worker's alert only), 'downgrade' (serve from the cheapest healthy model) or 'block' (402)"
)


class ApplicationCreate(NulStrippingModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None
    daily_cost_budget: float | None = Field(default=None, ge=0)
    budget_action: BudgetAction = Field(default="alert", description=_BUDGET_ACTION_HELP)


class ApplicationUpdate(NulStrippingModel):
    description: str | None = None
    daily_cost_budget: float | None = Field(default=None, ge=0)
    budget_action: BudgetAction | None = Field(default=None, description=_BUDGET_ACTION_HELP)


class ApplicationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    description: str | None
    daily_cost_budget: float | None
    budget_action: str
    created_at: datetime


class BudgetStatusOut(BaseModel):
    application_id: str
    daily_cost_budget: float | None
    budget_action: str
    spent_24h: float
    remaining: float | None
    exceeded: bool


class APIKeyCreate(NulStrippingModel):
    application_id: str = Field(max_length=36)
    name: str = Field(default="default", min_length=1, max_length=200)
    role: Literal["read", "write", "admin"] = "write"
    scoped_to_application: bool = Field(
        default=False,
        description="If true, this key can only see/write its own application's data",
    )
    expires_in_days: int | None = Field(
        default=None, ge=1, le=3650, description="The key stops working after this many days"
    )


class APIKeyRotate(NulStrippingModel):
    grace_minutes: int = Field(
        default=0,
        ge=0,
        le=10_080,
        description=(
            "Keep the old key working this long so clients can pick up the new one; 0 revokes "
            "it immediately"
        ),
    )
    expires_in_days: int | None = Field(
        default=None, ge=1, le=3650, description="A lifetime for the new key (default: none)"
    )


class APIKeyCreated(BaseModel):
    id: str
    name: str
    role: str
    key_prefix: str
    plaintext_key: str
    scoped_to_application: bool
    expires_at: datetime | None = None


class APIKeyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    application_id: str
    name: str
    role: str
    key_prefix: str
    revoked: bool
    revoked_at: datetime | None
    expires_at: datetime | None
    scoped_to_application: bool
    created_at: datetime
    last_used_at: datetime | None
