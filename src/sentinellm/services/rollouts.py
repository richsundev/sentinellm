"""Service logic for progressive model canary rollouts.

Split from `api/routers/rollouts.py` so `services/generation.py` (the
`/generate` request path) and `worker/tasks/rollout.py` can use it without
importing anything router-layer.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import ColumnElement, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from sentinellm.api.schemas.rollout import RolloutArmStats, RolloutCreate
from sentinellm.db.models import Evaluation, ModelPricing, ModelRollout, Trace


class RolloutConflictError(ValueError):
    """The rollout can't be created right now: the application already has an
    active (running/paused) rollout, or the challenger is flagged down."""


class RolloutModelNotFoundError(ValueError):
    """A rollout arm names a model that isn't in the model catalog."""


async def get_active_rollout(session: AsyncSession, application_id: str) -> ModelRollout | None:
    """The most recently created rollout for this application, regardless
    of stage — a terminal rollout keeps pinning traffic (100% at
    "promoted", 0% at "rolled_back") until a newer one supersedes it. Only
    "running" rows are still picked up by `worker.tasks.rollout`.
    """
    stmt = (
        select(ModelRollout)
        .where(ModelRollout.application_id == application_id)
        .order_by(ModelRollout.created_at.desc())
        .limit(1)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def create_rollout(session: AsyncSession, payload: RolloutCreate) -> ModelRollout:
    for model_id in (payload.incumbent_model, payload.challenger_model):
        pricing = await session.get(ModelPricing, model_id)
        if pricing is None:
            raise RolloutModelNotFoundError(f"model '{model_id}' is not in the model catalog")
        if model_id == payload.challenger_model and pricing.status == "down":
            raise RolloutConflictError(
                f"challenger '{model_id}' is currently flagged down — it would be rolled "
                "back immediately"
            )

    existing = await get_active_rollout(session, payload.application_id)
    if existing is not None and existing.stage in ("running", "paused"):
        raise RolloutConflictError(
            f"application '{payload.application_id}' already has an active rollout "
            f"({existing.id}, stage={existing.stage}) — pause, promote, or roll it back first"
        )

    rollout = ModelRollout(
        application_id=payload.application_id,
        incumbent_model=payload.incumbent_model,
        challenger_model=payload.challenger_model,
        traffic_pct=payload.initial_pct,
        quality_floor=payload.quality_floor,
        max_quality_regression=payload.max_quality_regression,
        max_error_rate=payload.max_error_rate,
        min_sample_size=payload.min_sample_size,
        step_pct=payload.step_pct,
        max_pct=payload.max_pct,
    )
    session.add(rollout)
    try:
        await session.flush()
    except IntegrityError as exc:
        # Two concurrent creates can both pass the check above; the partial
        # unique index `uq_model_rollouts_one_active_per_app` is the real
        # guarantee, this maps its violation to the same conflict.
        raise RolloutConflictError(
            f"application '{payload.application_id}' already has an active rollout"
        ) from exc
    return rollout


@dataclass(frozen=True, slots=True)
class ArmWindow:
    """One arm's traffic over a time window, with the evaluated-quality
    scores of whichever of those traces have been evaluated so far."""

    traces: list[Trace]
    quality_scores: list[float]

    @property
    def request_count(self) -> int:
        return len(self.traces)

    @property
    def error_rate(self) -> float:
        if not self.traces:
            return 0.0
        return sum(1 for t in self.traces if t.status == "error") / len(self.traces)

    @property
    def evaluated_count(self) -> int:
        return len(self.quality_scores)

    @property
    def avg_quality(self) -> float | None:
        if not self.quality_scores:
            return None
        return sum(self.quality_scores) / len(self.quality_scores)


async def load_window(
    session: AsyncSession,
    conditions: Sequence[ColumnElement[bool]],
    *,
    since: datetime,
    until: datetime | None = None,
) -> ArmWindow:
    """Traces matching `conditions` with `since < created_at <= until` (no upper
    bound when `until` is omitted), plus their evaluated-quality scores."""
    stmt = select(Trace).where(*conditions, Trace.created_at > since)
    if until is not None:
        stmt = stmt.where(Trace.created_at <= until)
    traces = list((await session.execute(stmt)).scalars().all())
    if not traces:
        return ArmWindow(traces=[], quality_scores=[])

    trace_ids = [t.id for t in traces]
    scores = (
        (
            await session.execute(
                select(Evaluation.overall_quality).where(Evaluation.trace_id.in_(trace_ids))
            )
        )
        .scalars()
        .all()
    )
    return ArmWindow(traces=traces, quality_scores=list(scores))


async def load_arm_window(
    session: AsyncSession,
    *,
    application_id: str,
    model: str,
    since: datetime,
    until: datetime | None = None,
) -> ArmWindow:
    """One model arm's traffic for an application (see `load_window`)."""
    return await load_window(
        session,
        [Trace.application_id == application_id, Trace.model == model],
        since=since,
        until=until,
    )


async def compute_arm_stats(
    session: AsyncSession, *, application_id: str, model: str, since: datetime
) -> RolloutArmStats:
    window = await load_arm_window(session, application_id=application_id, model=model, since=since)
    if not window.traces:
        return RolloutArmStats(
            model=model,
            request_count=0,
            error_rate=0.0,
            avg_quality=None,
            avg_latency_ms=0.0,
            avg_cost=0.0,
        )
    avg_quality = window.avg_quality
    return RolloutArmStats(
        model=model,
        request_count=window.request_count,
        error_rate=round(window.error_rate, 4),
        avg_quality=round(avg_quality, 4) if avg_quality is not None else None,
        avg_latency_ms=round(sum(t.latency_ms for t in window.traces) / window.request_count, 2),
        avg_cost=round(sum(t.estimated_cost for t in window.traces) / window.request_count, 6),
    )
