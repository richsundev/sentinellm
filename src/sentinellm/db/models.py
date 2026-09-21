"""SQLAlchemy 2.0 ORM models for every table in the platform.

Table inventory: applications, api_keys, traces, trace_spans, evaluations,
evaluation_metrics, hallucination_claims, datasets, dataset_records,
experiments, prompt_versions, models, routing_decisions, regressions, alerts,
semantic_cache_entries, model_rollouts, prompt_rollouts.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from sentinellm.core.ids import new_uuid
from sentinellm.db.base import Base, TimestampMixin, utcnow


class Application(Base, TimestampMixin):
    """A registered client application that submits traces."""

    __tablename__ = "applications"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    name: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, default=None)
    daily_cost_budget: Mapped[float | None] = mapped_column(Float, default=None)

    api_keys: Mapped[list[APIKey]] = relationship(back_populates="application")


class APIKey(Base, TimestampMixin):
    """Hashed API key. The plaintext key is only ever returned once, at creation."""

    __tablename__ = "api_keys"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    application_id: Mapped[str] = mapped_column(ForeignKey("applications.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(200), default="default")
    key_hash: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)
    key_prefix: Mapped[str] = mapped_column(String(32), nullable=False)
    role: Mapped[str] = mapped_column(String(20), default="write")  # read | write | admin
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)
    scoped_to_application: Mapped[bool] = mapped_column(Boolean, default=False)

    application: Mapped[Application] = relationship(back_populates="api_keys")


class Trace(Base, TimestampMixin):
    __tablename__ = "traces"
    __table_args__ = (
        UniqueConstraint("trace_id", name="uq_traces_trace_id"),
        Index("ix_traces_application_created", "application_id", "created_at"),
        Index("ix_traces_model_created", "model", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    trace_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    request_id: Mapped[str] = mapped_column(String(64), nullable=False)
    application_id: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    environment: Mapped[str] = mapped_column(String(50), default="production")

    model: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)

    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    system_prompt: Mapped[str | None] = mapped_column(Text, default=None)
    response: Mapped[str] = mapped_column(Text, default="")

    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    latency_ms: Mapped[float] = mapped_column(Float, default=0.0)
    estimated_cost: Mapped[float] = mapped_column(Float, default=0.0)

    retrieved_documents: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    trace_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    status: Mapped[str] = mapped_column(String(20), default="ok")  # ok | error
    error: Mapped[str | None] = mapped_column(Text, default=None)

    cache_hit: Mapped[bool] = mapped_column(Boolean, default=False)
    similarity_score: Mapped[float | None] = mapped_column(Float, default=None)

    tags: Mapped[list[str]] = mapped_column(JSON, default=list)

    evaluation_status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    # pending | evaluating | completed | failed

    prompt_id: Mapped[str | None] = mapped_column(String(200), default=None)
    prompt_version: Mapped[int | None] = mapped_column(Integer, default=None)

    spans: Mapped[list[TraceSpan]] = relationship(
        back_populates="trace", cascade="all, delete-orphan", order_by="TraceSpan.start_ms"
    )
    evaluation: Mapped[Evaluation | None] = relationship(
        back_populates="trace", cascade="all, delete-orphan", uselist=False
    )
    routing_decision: Mapped[RoutingDecision | None] = relationship(
        back_populates="trace", cascade="all, delete-orphan", uselist=False
    )
    feedback: Mapped[TraceFeedback | None] = relationship(
        back_populates="trace", cascade="all, delete-orphan", uselist=False
    )


class TraceSpan(Base):
    __tablename__ = "trace_spans"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    trace_id: Mapped[str] = mapped_column(ForeignKey("traces.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    start_ms: Mapped[float] = mapped_column(Float, default=0.0)
    duration_ms: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(20), default="ok")
    span_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    trace: Mapped[Trace] = relationship(back_populates="spans")


class Evaluation(Base, TimestampMixin):
    __tablename__ = "evaluations"
    __table_args__ = (UniqueConstraint("trace_id", name="uq_evaluations_trace_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    trace_id: Mapped[str] = mapped_column(ForeignKey("traces.id"), nullable=False)
    overall_quality: Mapped[float] = mapped_column(Float, default=0.0)
    hallucination_score: Mapped[float] = mapped_column(Float, default=0.0)
    evaluator_version: Mapped[str] = mapped_column(String(20), default="v1")

    trace: Mapped[Trace] = relationship(back_populates="evaluation")

    @property
    def public_trace_id(self) -> str:
        """The externally-visible `trace_id` (as opposed to `trace_id`, the
        internal FK to `traces.id`) — what the API and dashboard use."""
        return self.trace.trace_id if self.trace is not None else self.trace_id

    metrics: Mapped[list[EvaluationMetric]] = relationship(
        back_populates="evaluation", cascade="all, delete-orphan"
    )
    claims: Mapped[list[HallucinationClaim]] = relationship(
        back_populates="evaluation", cascade="all, delete-orphan"
    )


class EvaluationMetric(Base):
    __tablename__ = "evaluation_metrics"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    evaluation_id: Mapped[str] = mapped_column(ForeignKey("evaluations.id"), nullable=False)
    metric_name: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    threshold: Mapped[float | None] = mapped_column(Float, default=None)
    passed: Mapped[bool | None] = mapped_column(Boolean, default=None)
    reason: Mapped[str] = mapped_column(Text, default="")
    evaluator_version: Mapped[str] = mapped_column(String(20), default="v1")

    evaluation: Mapped[Evaluation] = relationship(back_populates="metrics")


class HallucinationClaim(Base):
    __tablename__ = "hallucination_claims"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    evaluation_id: Mapped[str] = mapped_column(ForeignKey("evaluations.id"), nullable=False)
    claim: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    support_score: Mapped[float] = mapped_column(Float, default=0.0)
    evidence: Mapped[str] = mapped_column(Text, default="")

    evaluation: Mapped[Evaluation] = relationship(back_populates="claims")


class Dataset(Base, TimestampMixin):
    __tablename__ = "datasets"
    __table_args__ = (UniqueConstraint("name", "version", name="uq_dataset_name_version"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    version: Mapped[str] = mapped_column(String(50), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, default=None)

    records: Mapped[list[DatasetRecord]] = relationship(
        back_populates="dataset", cascade="all, delete-orphan"
    )


class DatasetRecord(Base):
    __tablename__ = "dataset_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    dataset_id: Mapped[str] = mapped_column(ForeignKey("datasets.id"), nullable=False, index=True)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    context: Mapped[str] = mapped_column(Text, default="")
    expected_answer: Mapped[str] = mapped_column(Text, default="")
    record_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    dataset: Mapped[Dataset] = relationship(back_populates="records")


class PromptVersion(Base, TimestampMixin):
    __tablename__ = "prompt_versions"
    __table_args__ = (UniqueConstraint("prompt_id", "version", name="uq_prompt_id_version"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    prompt_id: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    template: Mapped[str] = mapped_column(Text, nullable=False)
    variables: Mapped[list[str]] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(20), default="draft")
    # draft | testing | production | deprecated
    author: Mapped[str] = mapped_column(String(200), default="unknown")
    prompt_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class ModelPricing(Base, TimestampMixin):
    __tablename__ = "models"

    id: Mapped[str] = mapped_column(String(100), primary_key=True)  # e.g. "openai:gpt-4o-mini"
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    input_price_per_1k: Mapped[float] = mapped_column(Float, default=0.0)
    output_price_per_1k: Mapped[float] = mapped_column(Float, default=0.0)
    cached_input_price_per_1k: Mapped[float | None] = mapped_column(Float, default=None)
    context_window: Mapped[int] = mapped_column(Integer, default=8192)
    quality_tier: Mapped[float] = mapped_column(Float, default=0.5)  # prior, 0-1
    avg_latency_ms_prior: Mapped[float] = mapped_column(Float, default=800.0)
    status: Mapped[str] = mapped_column(String(20), default="healthy")
    # healthy | degraded | down
    status_auto: Mapped[bool] = mapped_column(Boolean, default=True)
    status_reason: Mapped[str | None] = mapped_column(Text, default=None)


class RoutingDecision(Base, TimestampMixin):
    __tablename__ = "routing_decisions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    trace_id: Mapped[str] = mapped_column(ForeignKey("traces.id"), nullable=False)
    selected_model: Mapped[str] = mapped_column(String(100), nullable=False)
    reason: Mapped[str] = mapped_column(Text, default="")
    candidates: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    task_complexity: Mapped[str] = mapped_column(String(20), default="medium")
    risk_level: Mapped[str] = mapped_column(String(20), default="low")

    trace: Mapped[Trace] = relationship(back_populates="routing_decision")

    @property
    def public_trace_id(self) -> str:
        return self.trace.trace_id if self.trace is not None else self.trace_id


class TraceFeedback(Base, TimestampMixin):
    """A human reviewer's verdict on one trace — thumbs up/down + an optional
    note. One row per trace (upserted by the API, not appended), so this
    records a reviewer's *current* judgment rather than a full history of
    every reviewer's opinion — the simpler model, since the platform doesn't
    yet have multi-reviewer identity to disambiguate against.
    """

    __tablename__ = "trace_feedback"
    __table_args__ = (UniqueConstraint("trace_id", name="uq_trace_feedback_trace_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    trace_id: Mapped[str] = mapped_column(ForeignKey("traces.id"), nullable=False)
    rating: Mapped[str] = mapped_column(String(10), nullable=False)  # "up" | "down"
    note: Mapped[str | None] = mapped_column(Text, default=None)

    trace: Mapped[Trace] = relationship(back_populates="feedback")

    @property
    def public_trace_id(self) -> str:
        return self.trace.trace_id if self.trace is not None else self.trace_id


class Regression(Base):
    __tablename__ = "regressions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    metric_name: Mapped[str] = mapped_column(String(100), nullable=False)
    previous_value: Mapped[float] = mapped_column(Float, nullable=False)
    new_value: Mapped[float] = mapped_column(Float, nullable=False)
    delta_pct: Mapped[float] = mapped_column(Float, nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False)
    application_id: Mapped[str] = mapped_column(String(200), nullable=False)
    likely_cause: Mapped[str] = mapped_column(Text, default="")
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Alert(Base):
    __tablename__ = "alerts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    rule: Mapped[str] = mapped_column(String(200), nullable=False)
    current_value: Mapped[float] = mapped_column(Float, nullable=False)
    threshold: Mapped[float] = mapped_column(Float, nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False)
    affected_service: Mapped[str] = mapped_column(String(100), nullable=False)
    affected_model: Mapped[str | None] = mapped_column(String(100), default=None)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AlertRuleConfig(Base, TimestampMixin):
    """Configurable threshold for one alert rule (distinct from `Alert`,
    which records a firing — this table holds the *rule definition* an
    operator can tune from the Settings page instead of only via env vars).
    """

    __tablename__ = "alert_rules"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    rule: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    threshold: Mapped[float] = mapped_column(Float, nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    description: Mapped[str] = mapped_column(Text, default="")


class SemanticCacheEntry(Base, TimestampMixin):
    __tablename__ = "semantic_cache_entries"
    __table_args__ = (Index("ix_cache_application_model", "application_id", "model"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    application_id: Mapped[str] = mapped_column(String(200), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    query_text: Mapped[str] = mapped_column(Text, nullable=False)
    # Fingerprint of everything besides the question that shaped the answer
    # (system prompt + retrieved context). Entries only match a lookup with the
    # same key, so a RAG answer is never replayed against different documents.
    context_key: Mapped[str] = mapped_column(
        String(64), nullable=False, default="", server_default=""
    )
    embedding: Mapped[list[float]] = mapped_column(JSON, nullable=False)
    response: Mapped[str] = mapped_column(Text, nullable=False)
    hit_count: Mapped[int] = mapped_column(Integer, default=0)


class Experiment(Base, TimestampMixin):
    __tablename__ = "experiments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    prompt_id: Mapped[str] = mapped_column(String(200), nullable=False)
    prompt_version: Mapped[int] = mapped_column(Integer, nullable=False)
    dataset_id: Mapped[str] = mapped_column(ForeignKey("datasets.id"), nullable=False)

    faithfulness: Mapped[float] = mapped_column(Float, default=0.0)
    relevance: Mapped[float] = mapped_column(Float, default=0.0)
    hallucination_rate: Mapped[float] = mapped_column(Float, default=0.0)
    p95_latency_ms: Mapped[float] = mapped_column(Float, default=0.0)
    cost_per_request: Mapped[float] = mapped_column(Float, default=0.0)
    pass_rate: Mapped[float] = mapped_column(Float, default=0.0)

    git_commit: Mapped[str] = mapped_column(String(40), default="unknown")
    parameters: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class ModelRollout(Base, TimestampMixin):
    """A progressive canary rollout of a `challenger_model` against the
    current `incumbent_model` for one application's un-pinned traffic
    (requests to `/generate` that don't set `preferred_model` explicitly —
    see `services.generation.generate`).

    This is the platform's one closed autonomous loop: `traffic_pct` of
    that traffic is probabilistically routed to the challenger, and
    `worker.tasks.rollout.evaluate_rollouts` inspects the challenger's real
    trailing error rate / evaluated quality (and either arm's model-health
    status) on each pass to step `traffic_pct` up, auto-promote at
    `max_pct`, or auto-rollback to 0% — with zero human intervention unless
    `stage` is manually paused/promoted/rolled back via the API.

    A rollout keeps influencing routing for its application even after
    reaching a terminal `stage` ("promoted" pins traffic at `max_pct`,
    "rolled_back" pins it at 0%) — that's what makes the outcome durable;
    only "running" rows are still picked up by the evaluation loop.
    """

    __tablename__ = "model_rollouts"
    __table_args__ = (
        Index("ix_model_rollouts_application_created", "application_id", "created_at"),
        # At most one active (running/paused) rollout per application. The
        # service checks first for a friendly error; this index is what
        # actually holds under concurrent creates.
        Index(
            "uq_model_rollouts_one_active_per_app",
            "application_id",
            unique=True,
            postgresql_where=text("stage IN ('running', 'paused')"),
            sqlite_where=text("stage IN ('running', 'paused')"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    application_id: Mapped[str] = mapped_column(String(200), nullable=False)
    incumbent_model: Mapped[str] = mapped_column(String(100), nullable=False)
    challenger_model: Mapped[str] = mapped_column(String(100), nullable=False)
    traffic_pct: Mapped[float] = mapped_column(Float, default=0.0)
    stage: Mapped[str] = mapped_column(String(20), default="running")
    # running | paused | promoted | rolled_back
    quality_floor: Mapped[float] = mapped_column(Float, default=0.7)
    max_quality_regression: Mapped[float] = mapped_column(Float, default=0.1)
    max_error_rate: Mapped[float] = mapped_column(Float, default=0.1)
    min_sample_size: Mapped[int] = mapped_column(Integer, default=10)
    step_pct: Mapped[float] = mapped_column(Float, default=10.0)
    max_pct: Mapped[float] = mapped_column(Float, default=100.0)
    last_evaluated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
    outcome_reason: Mapped[str | None] = mapped_column(Text, default=None)


class PromptRollout(Base, TimestampMixin):
    """A progressive canary rollout of a `challenger_version` of one prompt
    against its `incumbent_version`, for one application's `/generate` traffic
    that serves that prompt (`prompt_variables` set) without pinning a
    `prompt_version`.

    It is the model rollout (`ModelRollout`) applied to the other thing that
    changes an LLM application's behaviour. `worker.tasks.prompt_rollout`
    judges the challenger's real error rate and evaluated quality against the
    same guard rails (`services.rollout_policy`) and steps `traffic_pct` up,
    promotes, or rolls back on its own.

    Scope is the application: the rollout decides which version *this
    application's* traffic is served and never changes a version's global
    `status`. Like a model rollout it keeps deciding after a terminal stage
    ("promoted" pins the challenger, "rolled_back" the incumbent) until a newer
    rollout for the same prompt supersedes it.
    """

    __tablename__ = "prompt_rollouts"
    __table_args__ = (
        Index("ix_prompt_rollouts_app_prompt_created", "application_id", "prompt_id", "created_at"),
        Index(
            "uq_prompt_rollouts_one_active",
            "application_id",
            "prompt_id",
            unique=True,
            postgresql_where=text("stage IN ('running', 'paused')"),
            sqlite_where=text("stage IN ('running', 'paused')"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    application_id: Mapped[str] = mapped_column(String(200), nullable=False)
    prompt_id: Mapped[str] = mapped_column(String(200), nullable=False)
    incumbent_version: Mapped[int] = mapped_column(Integer, nullable=False)
    challenger_version: Mapped[int] = mapped_column(Integer, nullable=False)
    traffic_pct: Mapped[float] = mapped_column(Float, default=0.0)
    stage: Mapped[str] = mapped_column(String(20), default="running")
    # running | paused | promoted | rolled_back
    quality_floor: Mapped[float] = mapped_column(Float, default=0.7)
    max_quality_regression: Mapped[float] = mapped_column(Float, default=0.1)
    max_error_rate: Mapped[float] = mapped_column(Float, default=0.1)
    min_sample_size: Mapped[int] = mapped_column(Integer, default=10)
    step_pct: Mapped[float] = mapped_column(Float, default=10.0)
    max_pct: Mapped[float] = mapped_column(Float, default=100.0)
    last_evaluated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
    outcome_reason: Mapped[str | None] = mapped_column(Text, default=None)
