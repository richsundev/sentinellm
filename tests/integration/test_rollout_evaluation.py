from datetime import UTC, datetime, timedelta

import pytest
from prometheus_client import REGISTRY
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sentinellm.core.ids import new_trace_id
from sentinellm.db.models import Alert, Evaluation, ModelPricing, ModelRollout, Trace
from sentinellm.worker.tasks.rollout import evaluate_rollouts

# Rollouts are evaluated over (last_decision, now - grace], so fixtures are
# backdated: the rollout started well before the evidence, and the evidence
# is comfortably older than the grace period.
_ROLLOUT_AGE = timedelta(minutes=10)
_TRACE_AGE = timedelta(minutes=1)


async def _make_rollout(db_session: AsyncSession, **overrides: object) -> ModelRollout:
    defaults: dict[str, object] = {
        "application_id": "rollout-app",
        "incumbent_model": "mock:incumbent",
        "challenger_model": "mock:challenger",
        "traffic_pct": 10.0,
        "stage": "running",
        "quality_floor": 0.7,
        "max_quality_regression": 0.1,
        "max_error_rate": 0.2,
        "min_sample_size": 5,
        "step_pct": 10.0,
        "max_pct": 50.0,
        "created_at": datetime.now(UTC) - _ROLLOUT_AGE,
    }
    defaults.update(overrides)
    rollout = ModelRollout(**defaults)
    db_session.add(rollout)
    await db_session.commit()
    return rollout


async def _make_trace(
    db_session: AsyncSession,
    rollout: ModelRollout,
    *,
    arm: str = "challenger",
    status: str = "ok",
    quality: float | None = None,
    age: timedelta = _TRACE_AGE,
) -> None:
    trace = Trace(
        trace_id=new_trace_id(),
        request_id="req",
        application_id=rollout.application_id,
        model=rollout.challenger_model if arm == "challenger" else rollout.incumbent_model,
        provider="mock",
        prompt="q",
        response="a",
        status=status,
        latency_ms=100.0,
        estimated_cost=0.001,
        evaluation_status="pending",
        created_at=datetime.now(UTC) - age,
    )
    db_session.add(trace)
    await db_session.flush()
    if quality is not None:
        db_session.add(Evaluation(trace_id=trace.id, overall_quality=quality))
    await db_session.commit()


def _decisions(decision: str) -> float:
    return (
        REGISTRY.get_sample_value("sentinel_rollout_decisions_total", {"decision": decision}) or 0.0
    )


@pytest.mark.asyncio
async def test_below_min_sample_size_is_not_evaluated(db_session: AsyncSession) -> None:
    rollout = await _make_rollout(db_session)
    for _ in range(3):
        await _make_trace(db_session, rollout)

    changed = await evaluate_rollouts(db_session)
    assert changed == []
    await db_session.refresh(rollout)
    assert rollout.traffic_pct == 10.0
    assert rollout.stage == "running"
    assert rollout.last_evaluated_at is None


@pytest.mark.asyncio
async def test_thin_windows_accumulate_across_passes(db_session: AsyncSession) -> None:
    """Regression: the evidence cursor used to advance on *every* pass, even
    one that decided nothing, so a rollout seeing fewer than min_sample_size
    requests per pass discarded them and could never advance."""
    rollout = await _make_rollout(db_session, min_sample_size=5)
    for _ in range(3):
        await _make_trace(db_session, rollout, quality=0.9)
    assert await evaluate_rollouts(db_session) == []

    for _ in range(3):
        await _make_trace(db_session, rollout, quality=0.9)
    changed = await evaluate_rollouts(db_session)

    assert len(changed) == 1
    assert changed[0].traffic_pct == 20.0
    assert "6 healthy challenger requests" in (changed[0].outcome_reason or "")


@pytest.mark.asyncio
async def test_undecided_rollout_keeps_its_cursor_when_another_rollout_decides(
    db_session: AsyncSession,
) -> None:
    """Regression: the cursor bump for a rollout that hadn't decided was
    persisted whenever *another* rollout in the same pass committed."""
    ready = await _make_rollout(db_session, application_id="ready-app")
    thin = await _make_rollout(db_session, application_id="thin-app")
    for _ in range(5):
        await _make_trace(db_session, ready, quality=0.9)
    await _make_trace(db_session, thin, quality=0.9)

    changed = await evaluate_rollouts(db_session)

    assert [r.application_id for r in changed] == ["ready-app"]
    await db_session.refresh(thin)
    assert thin.last_evaluated_at is None


@pytest.mark.asyncio
async def test_recent_traces_inside_the_grace_period_are_not_judged_yet(
    db_session: AsyncSession,
) -> None:
    rollout = await _make_rollout(db_session)
    for _ in range(5):
        await _make_trace(db_session, rollout, age=timedelta(seconds=2))

    assert await evaluate_rollouts(db_session) == []


@pytest.mark.asyncio
async def test_healthy_challenger_traffic_advances_traffic_pct(db_session: AsyncSession) -> None:
    rollout = await _make_rollout(db_session, traffic_pct=10.0, step_pct=10.0)
    for _ in range(5):
        await _make_trace(db_session, rollout, quality=0.9)
    before = _decisions("advance")

    changed = await evaluate_rollouts(db_session)

    assert len(changed) == 1
    assert changed[0].traffic_pct == 20.0
    assert changed[0].stage == "running"
    assert changed[0].last_evaluated_at is not None
    assert _decisions("advance") == before + 1


@pytest.mark.asyncio
async def test_a_decided_window_is_not_reused_by_the_next_pass(db_session: AsyncSession) -> None:
    rollout = await _make_rollout(db_session, traffic_pct=10.0, step_pct=10.0)
    for _ in range(5):
        await _make_trace(db_session, rollout, quality=0.9)

    await evaluate_rollouts(db_session)
    second = await evaluate_rollouts(db_session)

    assert second == []
    await db_session.refresh(rollout)
    assert rollout.traffic_pct == 20.0


@pytest.mark.asyncio
async def test_challenger_reaching_max_pct_is_promoted(db_session: AsyncSession) -> None:
    rollout = await _make_rollout(db_session, traffic_pct=45.0, step_pct=10.0, max_pct=50.0)
    for _ in range(5):
        await _make_trace(db_session, rollout, quality=0.9)
    before = _decisions("promote")

    changed = await evaluate_rollouts(db_session)

    assert changed[0].traffic_pct == 50.0
    assert changed[0].stage == "promoted"
    assert _decisions("promote") == before + 1


@pytest.mark.asyncio
async def test_high_error_rate_triggers_auto_rollback(db_session: AsyncSession) -> None:
    rollout = await _make_rollout(db_session, max_error_rate=0.2)
    for _ in range(4):
        await _make_trace(db_session, rollout, status="ok", quality=0.9)
    for _ in range(3):
        await _make_trace(db_session, rollout, status="error")
    before = _decisions("rollback")

    changed = await evaluate_rollouts(db_session)

    assert changed[0].stage == "rolled_back"
    assert changed[0].traffic_pct == 0.0
    assert "error_rate" in (changed[0].outcome_reason or "")
    assert _decisions("rollback") == before + 1


@pytest.mark.asyncio
async def test_low_quality_triggers_auto_rollback(db_session: AsyncSession) -> None:
    rollout = await _make_rollout(db_session, quality_floor=0.7)
    for _ in range(5):
        await _make_trace(db_session, rollout, quality=0.3)

    changed = await evaluate_rollouts(db_session)

    assert changed[0].stage == "rolled_back"
    assert changed[0].traffic_pct == 0.0
    assert "floor" in (changed[0].outcome_reason or "")


@pytest.mark.asyncio
async def test_challenger_worse_than_incumbent_is_rolled_back_even_above_the_floor(
    db_session: AsyncSession,
) -> None:
    """0.75 clears the absolute 0.7 floor, but the incumbent scored 0.95 over
    the same window — a 0.20 regression against a 0.10 allowance."""
    rollout = await _make_rollout(db_session, quality_floor=0.7, max_quality_regression=0.1)
    for _ in range(5):
        await _make_trace(db_session, rollout, arm="challenger", quality=0.75)
        await _make_trace(db_session, rollout, arm="incumbent", quality=0.95)

    changed = await evaluate_rollouts(db_session)

    assert changed[0].stage == "rolled_back"
    assert "incumbent" in (changed[0].outcome_reason or "")
    alert = (await db_session.execute(select(Alert))).scalars().one()
    assert alert.current_value == pytest.approx(0.75)
    assert alert.threshold == pytest.approx(0.85)


@pytest.mark.asyncio
async def test_challenger_within_the_regression_allowance_advances(
    db_session: AsyncSession,
) -> None:
    rollout = await _make_rollout(db_session, quality_floor=0.7, max_quality_regression=0.1)
    for _ in range(5):
        await _make_trace(db_session, rollout, arm="challenger", quality=0.88)
        await _make_trace(db_session, rollout, arm="incumbent", quality=0.95)

    changed = await evaluate_rollouts(db_session)

    assert changed[0].stage == "running"
    assert changed[0].traffic_pct == 20.0


@pytest.mark.asyncio
async def test_relative_gate_needs_enough_incumbent_evidence(db_session: AsyncSession) -> None:
    rollout = await _make_rollout(db_session, min_sample_size=5)
    for _ in range(5):
        await _make_trace(db_session, rollout, arm="challenger", quality=0.75)
    # Only two evaluated incumbent traces (< min_sample_size): not a baseline.
    for _ in range(2):
        await _make_trace(db_session, rollout, arm="incumbent", quality=0.99)

    changed = await evaluate_rollouts(db_session)

    assert changed[0].stage == "running"
    assert changed[0].traffic_pct == 20.0


@pytest.mark.asyncio
async def test_quality_gates_need_enough_evaluated_traces(db_session: AsyncSession) -> None:
    """Five requests but only two evaluated (and badly): that's two noisy
    scores, not evidence — the pass judges on error rate alone."""
    rollout = await _make_rollout(db_session, min_sample_size=5, quality_floor=0.7)
    for _ in range(2):
        await _make_trace(db_session, rollout, quality=0.1)
    for _ in range(3):
        await _make_trace(db_session, rollout)

    changed = await evaluate_rollouts(db_session)

    assert changed[0].stage == "running"
    assert changed[0].traffic_pct == 20.0


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
        await _make_trace(db_session, rollout, status="error")

    changed = await evaluate_rollouts(db_session)

    assert changed == []
    await db_session.refresh(rollout)
    assert rollout.stage == "paused"


@pytest.mark.asyncio
async def test_rollback_fires_an_alert_and_counts_it(db_session: AsyncSession) -> None:
    rollout = await _make_rollout(db_session, max_error_rate=0.1)
    for _ in range(5):
        await _make_trace(db_session, rollout, status="error")
    labels = {"rule": "rollout_auto_rollback", "severity": "high"}
    before = REGISTRY.get_sample_value("sentinel_alerts_fired_total", labels) or 0.0

    await evaluate_rollouts(db_session)

    alerts = (
        (await db_session.execute(select(Alert).where(Alert.rule == "rollout_auto_rollback")))
        .scalars()
        .all()
    )
    assert len(alerts) == 1
    assert alerts[0].affected_model == "mock:challenger"
    assert REGISTRY.get_sample_value("sentinel_alerts_fired_total", labels) == before + 1
