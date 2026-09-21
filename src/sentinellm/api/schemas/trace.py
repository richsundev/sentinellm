from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from sentinellm.api.schemas.common import NulStrippingModel


class RetrievedDocumentIn(NulStrippingModel):
    doc_id: str
    content: str
    score: float = 0.0
    rank: int = Field(default=0, ge=0, le=2_147_483_647)


class SpanIn(NulStrippingModel):
    name: str
    start_ms: float = Field(ge=0)
    duration_ms: float = Field(ge=0)
    status: str = "ok"
    metadata: dict[str, Any] = Field(default_factory=dict)


class TraceCreate(NulStrippingModel):
    # Lengths match the columns: Postgres enforces them, SQLite does not.
    trace_id: str | None = Field(default=None, min_length=1, max_length=64)
    request_id: str | None = Field(default=None, min_length=1, max_length=64)
    application_id: str = Field(min_length=1, max_length=200)
    environment: str = Field(default="production", min_length=1, max_length=50)
    model: str = Field(min_length=1, max_length=100)
    provider: str = Field(min_length=1, max_length=50)
    prompt: str
    system_prompt: str | None = None
    response: str = ""
    # Counts, times, and cost feed every aggregate (totals, averages,
    # percentiles), so a negative value is not merely odd — it subtracts.
    input_tokens: int = Field(default=0, ge=0, le=2_147_483_647)
    output_tokens: int = Field(default=0, ge=0, le=2_147_483_647)
    latency_ms: float = Field(default=0.0, ge=0)
    estimated_cost: float | None = Field(default=None, ge=0)
    retrieved_documents: list[RetrievedDocumentIn] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    # Everything downstream compares against exactly "error"; any other
    # spelling would be silently counted as a success.
    status: Literal["ok", "error"] = "ok"
    error: str | None = None
    spans: list[SpanIn] = Field(default_factory=list)
    prompt_id: str | None = Field(default=None, max_length=200)
    prompt_version: int | None = Field(default=None, ge=1, le=2_147_483_647)
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


class TraceFeedbackIn(NulStrippingModel):
    rating: Literal["up", "down"]
    note: str | None = None


class TraceFeedbackOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    trace_id: str = Field(validation_alias="public_trace_id")
    rating: str
    note: str | None
    created_at: datetime


class TraceTagsIn(NulStrippingModel):
    tags: list[Annotated[str, StringConstraints(max_length=50)]] = Field(
        default_factory=list, max_length=20
    )


class TraceTagsOut(BaseModel):
    trace_id: str
    tags: list[str]


class TraceReplayIn(NulStrippingModel):
    model: str | None = Field(
        default=None, description="Force this model instead of letting the router pick one"
    )
    prompt_version: int | None = Field(
        default=None,
        ge=1,
        le=2_147_483_647,
        description="Override the original trace's prompt_version, same prompt_id",
    )
    use_cache: bool = False


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
    tags: list[str] = Field(default_factory=list)
