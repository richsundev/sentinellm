"""Service logic for progressive model canary rollouts.

Split from `api/routers/rollouts.py` so `services/generation.py` (the
`/generate` request path) can look up the active rollout for an application
without importing anything router-layer.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sentinellm.api.schemas.rollout import RolloutArmStats, RolloutCreate
from sentinellm.db.models import Evaluation, ModelRollout, Trace


class RolloutConflictError(ValueError):
    """Raised when an application already has an active (running/paused)
    rollout — only one canary test may run per application at a time."""


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
        max_error_rate=payload.max_error_rate,
        min_sample_size=payload.min_sample_size,
        step_pct=payload.step_pct,
        max_pct=payload.max_pct,
    )
    session.add(rollout)
    await session.flush()
    return rollout


async def compute_arm_stats(
    session: AsyncSession, *, application_id: str, model: str, since: datetime
) -> RolloutArmStats:
    traces = (
        (
            await session.execute(
                select(Trace).where(
                    Trace.application_id == application_id,
                    Trace.model == model,
                    Trace.created_at >= since,
                )
            )
        )
        .scalars()
        .all()
    )
    if not traces:
        return RolloutArmStats(
            model=model,
            request_count=0,
            error_rate=0.0,
            avg_quality=None,
            avg_latency_ms=0.0,
            avg_cost=0.0,
        )

    error_count = sum(1 for t in traces if t.status == "error")
    trace_ids = [t.id for t in traces]
    evaluations = (
        (await session.execute(select(Evaluation).where(Evaluation.trace_id.in_(trace_ids))))
        .scalars()
        .all()
    )
    avg_quality = (
        round(sum(e.overall_quality for e in evaluations) / len(evaluations), 4)
        if evaluations
        else None
    )
    return RolloutArmStats(
        model=model,
        request_count=len(traces),
        error_rate=round(error_count / len(traces), 4),
        avg_quality=avg_quality,
        avg_latency_ms=round(sum(t.latency_ms for t in traces) / len(traces), 2),
        avg_cost=round(sum(t.estimated_cost for t in traces) / len(traces), 6),
    )
