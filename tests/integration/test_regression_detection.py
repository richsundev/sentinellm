from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from sentinellm.db.models import Evaluation, Trace
from sentinellm.worker.tasks.regression import detect_regressions_for_application


async def _seed_window(
    db_session: AsyncSession,
    application_id: str,
    *,
    count: int,
    quality: float,
    model: str,
    start: datetime,
    prompt_version: int,
) -> None:
    salt = start.isoformat()
    for i in range(count):
        trace = Trace(
            trace_id=f"trc_{application_id}_{salt}_{i}",
            request_id=f"req_{i}",
            application_id=application_id,
            model=model,
            provider="mock",
            prompt="q",
            response="a",
            latency_ms=400.0,
            estimated_cost=0.001,
            evaluation_status="completed",
            prompt_id="support-answer",
            prompt_version=prompt_version,
            created_at=start + timedelta(seconds=i),
        )
        db_session.add(trace)
        await db_session.flush()
        evaluation = Evaluation(
            trace_id=trace.id, overall_quality=quality, hallucination_score=1 - quality
        )
        db_session.add(evaluation)
    await db_session.commit()


@pytest.mark.asyncio
async def test_detects_quality_regression_between_windows(db_session: AsyncSession) -> None:
    app_id = "support-bot"
    base = datetime.now(UTC) - timedelta(hours=2)
    await _seed_window(
        db_session,
        app_id,
        count=30,
        quality=0.93,
        model="mock:sentinel-pro",
        start=base,
        prompt_version=1,
    )
    await _seed_window(
        db_session,
        app_id,
        count=30,
        quality=0.82,
        model="mock:sentinel-flash",
        start=base + timedelta(minutes=90),
        prompt_version=2,
    )

    regressions = await detect_regressions_for_application(db_session, app_id)

    quality_regressions = [r for r in regressions if r.metric_name == "overall_quality"]
    assert len(quality_regressions) == 1
    regression = quality_regressions[0]
    assert regression.delta_pct >= 5.0
    assert regression.severity in {"low", "medium", "high", "critical"}
    assert "prompt" in regression.likely_cause or "model" in regression.likely_cause


@pytest.mark.asyncio
async def test_no_regression_when_quality_is_stable(db_session: AsyncSession) -> None:
    app_id = "stable-app"
    base = datetime.now(UTC) - timedelta(hours=2)
    await _seed_window(
        db_session,
        app_id,
        count=30,
        quality=0.90,
        model="mock:sentinel-pro",
        start=base,
        prompt_version=1,
    )
    await _seed_window(
        db_session,
        app_id,
        count=30,
        quality=0.905,
        model="mock:sentinel-pro",
        start=base + timedelta(minutes=90),
        prompt_version=1,
    )

    regressions = await detect_regressions_for_application(db_session, app_id)
    assert regressions == []


@pytest.mark.asyncio
async def test_not_enough_history_yields_no_regression(db_session: AsyncSession) -> None:
    app_id = "new-app"
    await _seed_window(
        db_session,
        app_id,
        count=5,
        quality=0.5,
        model="mock:sentinel-nano",
        start=datetime.now(UTC),
        prompt_version=1,
    )
    regressions = await detect_regressions_for_application(db_session, app_id)
    assert regressions == []
