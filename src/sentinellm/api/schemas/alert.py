from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from sentinellm.api.schemas.common import NulStrippingModel


class AlertRuleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    rule: str
    threshold: float
    severity: str
    enabled: bool
    description: str


class AlertRuleUpdate(NulStrippingModel):
    threshold: float | None = Field(default=None, ge=0)
    enabled: bool | None = Field(default=None)


class AlertOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    rule: str
    current_value: float
    threshold: float
    severity: str
    timestamp: datetime
    affected_service: str
    affected_model: str | None


class RegressionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    metric_name: str
    previous_value: float
    new_value: float
    delta_pct: float = Field(
        description=(
            "How much worse the metric got, in percent (0-100 scale, capped at 1000): always "
            "positive. Direction is in previous_value vs new_value — a latency or "
            "hallucination regression goes *up*."
        )
    )
    severity: str
    detected_at: datetime
    application_id: str
    likely_cause: str
