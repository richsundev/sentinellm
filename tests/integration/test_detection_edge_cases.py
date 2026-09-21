"""Edge cases in regression detection and alert dedupe found in review."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from sentinellm.core.ids import new_trace_id
from sentinellm.db.models import Alert, Evaluation, Regression, Trace
from sentinellm.worker.tasks.alerting import _already_alerted
from sentinellm.worker.tasks.regression import detect_regressions_for_application


async def _window(
    session: AsyncSession,
    app_id: str,
    *,
    count: int,
    quality: float,
    hallucination: float,
    start: datetime,
) -> None:
    for i in range(count):
        trace = Trace(
            trace_id=new_trace_id(),
            request_id="r",
            application_id=app_id,
            model="mock:m",
            provider="mock",
            prompt="q",
            response="a",
            latency_ms=100.0,
            estimated_cost=0.0,
            evaluation_status="completed",
            created_at=start + timedelta(seconds=i),
        )
        session.add(trace)
        await session.flush()
        session.add(
            Evaluation(
                trace_id=trace.id, overall_quality=quality, hallucination_score=hallucination
            )
        )
    await session.commit()


async def _two_windows(
    session: AsyncSession, app_id: str, *, before: float, after: float
) -> list[Regression]:
    base = datetime.now(UTC) - timedelta(hours=2)
    await _window(session, app_id, count=30, quality=0.8, hallucination=before, start=base)
    await _window(
        session,
        app_id,
        count=30,
        quality=0.8,
        hallucination=after,
        start=base + timedelta(minutes=90),
    )
    return await detect_regressions_for_application(session, app_id)


@pytest.mark.asyncio
async def test_hallucination_jump_from_a_perfectly_clean_baseline_is_flagged(
    db_session: AsyncSession,
) -> None:
    """A previous hallucination average of exactly 0 used to be skipped as a
    division-by-zero guard — so 'never hallucinated' -> 'hallucinates half the
    time' was the one case that could never be detected."""
    regressions = await _two_windows(db_session, "app-a", before=0.0, after=0.5)

    flagged = {r.metric_name: r for r in regressions}
    assert "hallucination_score" in flagged
    assert flagged["hallucination_score"].severity == "critical"
    assert flagged["hallucination_score"].previous_value == 0.0
    assert flagged["hallucination_score"].new_value == pytest.approx(0.5)


@pytest.mark.asyncio
async def test_noise_above_a_zero_baseline_is_not_flagged(db_session: AsyncSession) -> None:
    regressions = await _two_windows(db_session, "app-b", before=0.0, after=0.02)
    assert "hallucination_score" not in {r.metric_name for r in regressions}


@pytest.mark.asyncio
async def test_a_zero_baseline_can_not_regress_a_higher_is_better_metric(
    db_session: AsyncSession,
) -> None:
    base = datetime.now(UTC) - timedelta(hours=2)
    await _window(db_session, "app-c", count=30, quality=0.0, hallucination=0.0, start=base)
    await _window(
        db_session,
        "app-c",
        count=30,
        quality=0.9,
        hallucination=0.0,
        start=base + timedelta(minutes=90),
    )
    assert await detect_regressions_for_application(db_session, "app-c") == []


@pytest.mark.asyncio
async def test_duplicate_recent_regression_rows_do_not_crash_detection(
    db_session: AsyncSession,
) -> None:
    """The dedupe lookup used `scalar_one_or_none()`, which raises if more than
    one row matches — and two can exist (e.g. two racing replicas before the
    worker was serialised). That crashed every later pass."""
    for _ in range(2):
        db_session.add(
            Regression(
                metric_name="overall_quality",
                previous_value=0.9,
                new_value=0.5,
                delta_pct=44.0,
                severity="critical",
                application_id="app-d",
                likely_cause="x",
                detected_at=datetime.now(UTC),
            )
        )
    await db_session.commit()
    base = datetime.now(UTC) - timedelta(hours=2)
    await _window(db_session, "app-d", count=30, quality=0.9, hallucination=0.0, start=base)
    await _window(
        db_session,
        "app-d",
        count=30,
        quality=0.5,
        hallucination=0.0,
        start=base + timedelta(minutes=90),
    )

    regressions = await detect_regressions_for_application(db_session, "app-d")

    # overall_quality was already flagged (twice); it must simply be deduped.
    assert "overall_quality" not in {r.metric_name for r in regressions}


@pytest.mark.asyncio
async def test_duplicate_recent_alerts_do_not_crash_the_alert_dedupe_check(
    db_session: AsyncSession,
) -> None:
    for _ in range(2):
        db_session.add(
            Alert(
                rule="error_rate",
                current_value=0.5,
                threshold=0.05,
                severity="high",
                affected_service="sentinel-api",
                timestamp=datetime.now(UTC),
            )
        )
    await db_session.commit()

    assert await _already_alerted(db_session, "error_rate") is True
    assert await _already_alerted(db_session, "p95_latency") is False
