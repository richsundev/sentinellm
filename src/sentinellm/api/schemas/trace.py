from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class RetrievedDocumentIn(BaseModel):
    doc_id: str
    content: str
    score: float = 0.0
    rank: int = 0


class SpanIn(BaseModel):
    name: str
    start_ms: float
    duration_ms: float
    status: str = "ok"
    metadata: dict[str, Any] = Field(default_factory=dict)


class TraceCreate(BaseModel):
    trace_id: str | None = None
    request_id: str | None = None
    application_id: str
    environment: str = "production"
    model: str
    provider: str
    prompt: str
    system_prompt: str | None = None
    response: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: float = 0.0
    estimated_cost: float | None = None
    retrieved_documents: list[RetrievedDocumentIn] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    status: str = "ok"
    error: str | None = None
    spans: list[SpanIn] = Field(default_factory=list)
    prompt_id: str | None = None
    prompt_version: int | None = None
    evaluate: bool = True


class SpanOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    name: str
    start_ms: float
    duration_ms: float
    status: str
    metadata: dict[str, Any] = Field(validation_alias="span_metadata", default_factory=dict)


class EvaluationMetricOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    metric_name: str
    score: float
    threshold: float | None
    passed: bool | None
    reason: str
    evaluator_version: str


class HallucinationClaimOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    claim: str
    status: str
    support_score: float
    evidence: str


class HallucinationOut(BaseModel):
    hallucination_score: float
    claims: list[HallucinationClaimOut]


class EvaluationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    trace_id: str = Field(validation_alias="public_trace_id")
    overall_quality: float
    metrics: list[EvaluationMetricOut]
    hallucination: HallucinationOut | None = None
    created_at: datetime


class RoutingCandidateOut(BaseModel):
    model: str
    routing_score: float
    predicted_quality: float
    normalized_cost: float
    normalized_latency: float
    risk: float
    excluded_reason: str | None = None


class RoutingDecisionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    trace_id: str = Field(validation_alias="public_trace_id")
    selected_model: str
    reason: str
    candidates: list[RoutingCandidateOut]
    created_at: datetime


class TraceFeedbackIn(BaseModel):
    rating: Literal["up", "down"]
    note: str | None = None


class TraceFeedbackOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    trace_id: str = Field(validation_alias="public_trace_id")
    rating: str
    note: str | None
    created_at: datetime


class TraceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    trace_id: str
    request_id: str
    application_id: str
    environment: str
    model: str
    provider: str
    prompt: str
    system_prompt: str | None
    response: str
    input_tokens: int
    output_tokens: int
    latency_ms: float
    estimated_cost: float
    retrieved_documents: list[dict[str, Any]]
    metadata: dict[str, Any] = Field(validation_alias="trace_metadata")
    status: str
    error: str | None
    created_at: datetime
    spans: list[SpanOut] = Field(default_factory=list)
    evaluation: EvaluationOut | None = None
    routing_decision: RoutingDecisionOut | None = None
    feedback: TraceFeedbackOut | None = None
    cache_hit: bool
    similarity_score: float | None
