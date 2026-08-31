"""Per-model statistics feeding the router: observed quality/latency/
reliability from recent trace history, blended with the static catalog prior
until enough samples exist to trust the observed data.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from sentinellm.db.models import Evaluation, ModelPricing, Trace
from sentinellm.pricing.catalog import get_profile

_MIN_SAMPLES_FOR_TRUST = 5


@dataclass(frozen=True, slots=True)
class ModelStats:
    predicted_quality: float
    avg_latency_ms: float
    reliability: float
    sample_count: int
    status: str


class ModelStatsProvider(Protocol):
    async def get_stats(self, model_id: str) -> ModelStats: ...


class StaticModelStatsProvider:
    """Uses only the static catalog prior. Used in tests and before any
    trace history exists."""

    async def get_stats(self, model_id: str) -> ModelStats:
        profile = get_profile(model_id)
        return ModelStats(
            predicted_quality=profile.quality_tier,
            avg_latency_ms=profile.avg_latency_ms_prior,
            reliability=1.0,
            sample_count=0,
            status="healthy",
        )


class DBModelStatsProvider:
    """Blends the catalog prior with observed trace/evaluation history."""

    def __init__(self, session: AsyncSession, window: int = 200) -> None:
        self._session = session
        self._window = window

    async def get_stats(self, model_id: str) -> ModelStats:
        profile = get_profile(model_id)

        pricing_row = await self._session.get(ModelPricing, model_id)
        status = pricing_row.status if pricing_row else "healthy"

        recent_traces_stmt = (
            select(Trace.id, Trace.status, Trace.latency_ms)
            .where(Trace.model == model_id)
            .order_by(Trace.created_at.desc())
            .limit(self._window)
        )
        rows = (await self._session.execute(recent_traces_stmt)).all()
        sample_count = len(rows)

        if sample_count == 0:
            return ModelStats(profile.quality_tier, profile.avg_latency_ms_prior, 1.0, 0, status)

        success_count = sum(1 for r in rows if r.status == "ok")
        reliability = success_count / sample_count
        avg_latency = sum(r.latency_ms for r in rows) / sample_count

        trace_ids = [r.id for r in rows]
        quality_stmt = select(func.avg(Evaluation.overall_quality)).where(
            Evaluation.trace_id.in_(trace_ids)
        )
        observed_quality = (await self._session.execute(quality_stmt)).scalar()

        if observed_quality is not None and sample_count >= _MIN_SAMPLES_FOR_TRUST:
            trust = min(1.0, sample_count / (_MIN_SAMPLES_FOR_TRUST * 4))
            predicted_quality = observed_quality * trust + profile.quality_tier * (1 - trust)
        else:
            predicted_quality = profile.quality_tier

        if reliability < 0.5:
            status = "down"
        elif reliability < 0.85:
            status = "degraded" if status == "healthy" else status

        return ModelStats(
            predicted_quality=round(min(1.0, predicted_quality), 4),
            avg_latency_ms=round(avg_latency, 2),
            reliability=round(reliability, 4),
            sample_count=sample_count,
            status=status,
        )
