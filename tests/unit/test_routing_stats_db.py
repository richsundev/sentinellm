"""Regression tests for `DBModelStatsProvider`: health used to be inferred
from as little as ONE failed trace with no time window — and a model marked
down is excluded from routing, so it could never earn the traces needed to
recover. The registry's own quality/latency priors were also ignored."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from sentinellm.core.ids import new_trace_id
from sentinellm.db.models import ModelPricing, Trace
from sentinellm.routing.stats import DBModelStatsProvider


async def _add_traces(
    session: AsyncSession, model: str, *, ok: int, error: int, age: timedelta = timedelta()
) -> None:
    created = datetime.now(UTC) - age
    for i in range(ok + error):
        session.add(
            Trace(
                trace_id=new_trace_id(),
                request_id="r",
                application_id="app",
                model=model,
                provider="mock",
                prompt="q",
                response="a",
                status="ok" if i < ok else "error",
                latency_ms=100.0,
                evaluation_status="skipped",
                created_at=created,
            )
        )
    await session.commit()


@pytest.mark.asyncio
async def test_a_single_failed_trace_does_not_mark_a_model_down(db_session: AsyncSession) -> None:
    await _add_traces(db_session, "mock:sentinel-flash", ok=0, error=1)

    stats = await DBModelStatsProvider(db_session).get_stats("mock:sentinel-flash")

    assert stats.status == "healthy"


@pytest.mark.asyncio
async def test_a_few_failures_below_the_sample_floor_are_not_enough(
    db_session: AsyncSession,
) -> None:
    await _add_traces(db_session, "mock:sentinel-flash", ok=0, error=4)  # 100% failing, n=4

    stats = await DBModelStatsProvider(db_session).get_stats("mock:sentinel-flash")

    assert stats.status == "healthy"


@pytest.mark.asyncio
async def test_sustained_recent_failure_marks_a_model_down(db_session: AsyncSession) -> None:
    await _add_traces(db_session, "mock:sentinel-flash", ok=1, error=9)

    stats = await DBModelStatsProvider(db_session).get_stats("mock:sentinel-flash")

    assert stats.status == "down"


@pytest.mark.asyncio
async def test_old_failures_no_longer_count_so_a_model_can_recover(
    db_session: AsyncSession,
) -> None:
    """The failures are days old and the model, being excluded, got no new
    traffic since. It must be routable again."""
    await _add_traces(db_session, "mock:sentinel-flash", ok=0, error=10, age=timedelta(days=3))

    stats = await DBModelStatsProvider(db_session).get_stats("mock:sentinel-flash")

    assert stats.status == "healthy"


@pytest.mark.asyncio
async def test_registry_priors_drive_a_model_with_no_history(db_session: AsyncSession) -> None:
    """quality_tier / avg_latency_ms_prior set via POST /models are stored on
    the ModelPricing row; the router used a generic 0.6 / 600ms instead."""
    db_session.add(
        ModelPricing(
            id="acme:premium",
            name="premium",
            provider="acme",
            quality_tier=0.95,
            avg_latency_ms_prior=123.0,
        )
    )
    await db_session.commit()

    stats = await DBModelStatsProvider(db_session).get_stats("acme:premium")

    assert stats.predicted_quality == pytest.approx(0.95)
    assert stats.avg_latency_ms == pytest.approx(123.0)


@pytest.mark.asyncio
async def test_registry_prior_is_what_observed_quality_is_blended_with(
    db_session: AsyncSession,
) -> None:
    """With too few evaluated samples to trust, the prior alone is used."""
    db_session.add(
        ModelPricing(
            id="acme:premium",
            name="premium",
            provider="acme",
            quality_tier=0.42,
            avg_latency_ms_prior=500.0,
        )
    )
    await db_session.commit()
    await _add_traces(db_session, "acme:premium", ok=2, error=0)

    stats = await DBModelStatsProvider(db_session).get_stats("acme:premium")

    assert stats.predicted_quality == pytest.approx(0.42)


@pytest.mark.asyncio
async def test_models_without_a_registry_row_still_fall_back_to_the_catalog(
    db_session: AsyncSession,
) -> None:
    stats = await DBModelStatsProvider(db_session).get_stats("mock:sentinel-pro")
    assert stats.predicted_quality == pytest.approx(0.90)  # static catalog prior
