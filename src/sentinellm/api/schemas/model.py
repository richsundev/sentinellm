from __future__ import annotations

from pydantic import BaseModel, ConfigDict


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
