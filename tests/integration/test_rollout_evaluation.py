from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from sentinellm.core.ids import new_trace_id
from sentinellm.db.models import Evaluation, ModelPricing, ModelRollout, Trace
from sentinellm.worker.tasks.rollout import evaluate_rollouts


async def _make_rollout(db_session: AsyncSession, **overrides: object) -> ModelRollout:
    defaults: dict[str, object] = {
        "application_id": "rollout-app",
        "incumbent_model": "mock:incumbent",
        "challenger_model": "mock:challenger",
        "traffic_pct": 10.0,
        "stage": "running",
        "quality_floor": 0.7,
        "max_error_rate": 0.2,
        "min_sample_size": 5,
        "step_pct": 10.0,
        "max_pct": 50.0,
    }
    defaults.update(overrides)
    rollout = ModelRollout(**defaults)
    db_session.add(rollout)
    await db_session.commit()
    return rollout


async def _make_challenger_trace(
    db_session: AsyncSession,
    rollout: ModelRollout,
    *,
    status: str = "ok",
    quality: float | None = None,
) -> None:
    trace = Trace(
        trace_id=new_trace_id(),
        request_id="req",
        application_id=rollout.application_id,
        model=rollout.challenger_model,
        provider="mock",
        prompt="q",
        response="a",
        status=status,
        latency_ms=100.0,
        estimated_cost=0.001,
        evaluation_status="pending",
        created_at=datetime.now(UTC),
    )
    db_session.add(trace)
    await db_session.flush()
    if quality is not None:
        db_session.add(Evaluation(trace_id=trace.id, overall_quality=quality))
    await db_session.commit()


@pytest.mark.asyncio
async def test_below_min_sample_size_is_not_evaluated(db_session: AsyncSession) -> None:
    rollout = await _make_rollout(db_session)
    for _ in range(3):
        await _make_challenger_trace(db_session, rollout)

    changed = await evaluate_rollouts(db_session)
    assert changed == []
    await db_session.refresh(rollout)
    assert rollout.traffic_pct == 10.0
    assert rollout.stage == "running"


@pytest.mark.asyncio
async def test_healthy_challenger_traffic_advances_traffic_pct(db_session: AsyncSession) -> None:
    rollout = await _make_rollout(db_session, traffic_pct=10.0, step_pct=10.0)
    for _ in range(5):
        await _make_challenger_trace(db_session, rollout, quality=0.9)

    changed = await evaluate_rollouts(db_session)
    assert len(changed) == 1
    assert changed[0].traffic_pct == 20.0
    assert changed[0].stage == "running"


@pytest.mark.asyncio
async def test_challenger_reaching_max_pct_is_promoted(db_session: AsyncSession) -> None:
    rollout = await _make_rollout(db_session, traffic_pct=45.0, step_pct=10.0, max_pct=50.0)
    for _ in range(5):
        await _make_challenger_trace(db_session, rollout, quality=0.9)

    changed = await evaluate_rollouts(db_session)
    assert changed[0].traffic_pct == 50.0
    assert changed[0].stage == "promoted"


@pytest.mark.asyncio
async def test_high_error_rate_triggers_auto_rollback(db_session: AsyncSession) -> None:
    rollout = await _make_rollout(db_session, max_error_rate=0.2)
    for _ in range(4):
        await _make_challenger_trace(db_session, rollout, status="ok", quality=0.9)
    for _ in range(3):
        await _make_challenger_trace(db_session, rollout, status="error")

    changed = await evaluate_rollouts(db_session)
    assert changed[0].stage == "rolled_back"
    assert changed[0].traffic_pct == 0.0
    assert "error_rate" in (changed[0].outcome_reason or "")


@pytest.mark.asyncio
async def test_low_quality_triggers_auto_rollback(db_session: AsyncSession) -> None:
    rollout = await _make_rollout(db_session, quality_floor=0.7)
    for _ in range(5):
        await _make_challenger_trace(db_session, rollout, quality=0.3)

    changed = await evaluate_rollouts(db_session)
    assert changed[0].stage == "rolled_back"
    assert changed[0].traffic_pct == 0.0
    assert "avg_quality" in (changed[0].outcome_reason or "")


@pytest.mark.asyncio
async def test_unhealthy_challenger_model_triggers_immediate_rollback(
    db_session: AsyncSession,
) -> None:
    await _make_rollout(db_session, min_sample_size=100)
    db_session.add(
        ModelPricing(id="mock:challenger", name="challenger", provider="mock", status="down")
    )
    await db_session.commit()
    # Even with zero traffic (well below min_sample_size), a down model
    # must abort immediately rather than waiting for evidence.

    changed = await evaluate_rollouts(db_session)
    assert changed[0].stage == "rolled_back"
    assert "down" in (changed[0].outcome_reason or "")


@pytest.mark.asyncio
async def test_paused_rollout_is_not_evaluated(db_session: AsyncSession) -> None:
    rollout = await _make_rollout(db_session, stage="paused")
    for _ in range(10):
        await _make_challenger_trace(db_session, rollout, status="error")

    changed = await evaluate_rollouts(db_session)
    assert changed == []
    await db_session.refresh(rollout)
    assert rollout.stage == "paused"


@pytest.mark.asyncio
async def test_rollback_fires_an_alert(db_session: AsyncSession) -> None:
    from sqlalchemy import select

    from sentinellm.db.models import Alert

    rollout = await _make_rollout(db_session, max_error_rate=0.1)
    for _ in range(5):
        await _make_challenger_trace(db_session, rollout, status="error")

    await evaluate_rollouts(db_session)

    alerts = (
        (await db_session.execute(select(Alert).where(Alert.rule == "rollout_auto_rollback")))
        .scalars()
        .all()
    )
    assert len(alerts) == 1
    assert alerts[0].affected_model == "mock:challenger"
