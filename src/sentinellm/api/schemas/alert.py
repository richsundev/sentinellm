from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class AlertRuleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    rule: str
    threshold: float
    severity: str
    enabled: bool
    description: str


class AlertRuleUpdate(BaseModel):
    threshold: float | None = Field(default=None)
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
    delta_pct: float
    severity: str
    detected_at: datetime
    application_id: str
    likely_cause: str
