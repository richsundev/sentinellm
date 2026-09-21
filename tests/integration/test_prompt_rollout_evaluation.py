from datetime import UTC, datetime, timedelta

import pytest
from prometheus_client import REGISTRY
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sentinellm.core.ids import new_trace_id
from sentinellm.db.models import Alert, Evaluation, PromptRollout, PromptVersion, Trace
from sentinellm.worker.tasks.prompt_rollout import evaluate_prompt_rollouts

# As for model rollouts: evidence is read over (last_decision, now - grace], so
# fixtures are backdated past the grace period.
_ROLLOUT_AGE = timedelta(minutes=10)
_TRACE_AGE = timedelta(minutes=1)


async def _prompt(db: AsyncSession, version: int, status: str = "production") -> None:
    db.add(
        PromptVersion(
            prompt_id="support",
            version=version,
            template=f"v{version} {{{{question}}}}",
            status=status,
        )
    )
    await db.commit()


async def _rollout(db: AsyncSession, **overrides: object) -> PromptRollout:
    await _prompt(db, 1)
    await _prompt(db, 2, status="testing")
    defaults: dict[str, object] = {
        "application_id": "prompt-app",
        "prompt_id": "support",
        "incumbent_version": 1,
        "challenger_version": 2,
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
    rollout = PromptRollout(**defaults)
    db.add(rollout)
    await db.commit()
    return rollout


async def _trace(
    db: AsyncSession,
    rollout: PromptRollout,
    *,
    arm: str = "challenger",
    status: str = "ok",
    quality: float | None = None,
    application_id: str | None = None,
    prompt_id: str | None = None,
) -> None:
    trace = Trace(
        trace_id=new_trace_id(),
        request_id="req",
        application_id=application_id or rollout.application_id,
        model="mock:sentinel-flash",
        provider="mock",
        prompt="q",
        response="a",
        status=status,
        latency_ms=100.0,
        estimated_cost=0.001,
        prompt_id=prompt_id or rollout.prompt_id,
        prompt_version=rollout.challenger_version
        if arm == "challenger"
        else rollout.incumbent_version,
        evaluation_status="pending",
        created_at=datetime.now(UTC) - _TRACE_AGE,
    )
    db.add(trace)
    await db.flush()
    if quality is not None:
        db.add(Evaluation(trace_id=trace.id, overall_quality=quality))
    await db.commit()


def _decisions(decision: str) -> float:
    return (
        REGISTRY.get_sample_value("sentinel_prompt_rollout_decisions_total", {"decision": decision})
        or 0.0
    )


@pytest.mark.asyncio
async def test_below_min_sample_size_is_not_evaluated(db_session: AsyncSession) -> None:
    rollout = await _rollout(db_session)
    for _ in range(3):
        await _trace(db_session, rollout)

    assert await evaluate_prompt_rollouts(db_session) == []

    await db_session.refresh(rollout)
    assert (rollout.traffic_pct, rollout.stage, rollout.last_evaluated_at) == (
        10.0,
        "running",
        None,
    )


@pytest.mark.asyncio
async def test_healthy_challenger_traffic_steps_the_rollout_up(db_session: AsyncSession) -> None:
    rollout = await _rollout(db_session)
    before = _decisions("advance")
    for _ in range(6):
        await _trace(db_session, rollout, quality=0.9)
        await _trace(db_session, rollout, arm="incumbent", quality=0.9)

    changed = await evaluate_prompt_rollouts(db_session)

    assert [r.id for r in changed] == [rollout.id]
    assert rollout.traffic_pct == 20.0
    assert rollout.stage == "running"
    assert "advanced to 20%" in (rollout.outcome_reason or "")
    assert _decisions("advance") == before + 1


@pytest.mark.asyncio
async def test_reaching_the_ceiling_promotes(db_session: AsyncSession) -> None:
    rollout = await _rollout(db_session, traffic_pct=45.0, max_pct=50.0)
    for _ in range(6):
        await _trace(db_session, rollout, quality=0.9)

    await evaluate_prompt_rollouts(db_session)

    assert (rollout.stage, rollout.traffic_pct) == ("promoted", 50.0)
    assert "promoted" in (rollout.outcome_reason or "")


@pytest.mark.asyncio
async def test_a_high_error_rate_rolls_the_challenger_back_and_alerts(
    db_session: AsyncSession,
) -> None:
    rollout = await _rollout(db_session)
    before = _decisions("rollback")
    for _ in range(4):
        await _trace(db_session, rollout, status="error")
    for _ in range(2):
        await _trace(db_session, rollout)

    await evaluate_prompt_rollouts(db_session)

    assert (rollout.stage, rollout.traffic_pct) == ("rolled_back", 0.0)
    assert "error_rate" in (rollout.outcome_reason or "")
    alert = (await db_session.execute(select(Alert))).scalar_one()
    assert alert.rule == "prompt_rollout_auto_rollback"
    assert alert.affected_model == "support@v2"
    assert _decisions("rollback") == before + 1


@pytest.mark.asyncio
async def test_quality_below_the_floor_rolls_back(db_session: AsyncSession) -> None:
    rollout = await _rollout(db_session)
    for _ in range(6):
        await _trace(db_session, rollout, quality=0.4)

    await evaluate_prompt_rollouts(db_session)

    assert rollout.stage == "rolled_back"
    assert "floor" in (rollout.outcome_reason or "")


@pytest.mark.asyncio
async def test_a_regression_against_the_incumbent_version_rolls_back(
    db_session: AsyncSession,
) -> None:
    rollout = await _rollout(db_session, quality_floor=0.5, max_quality_regression=0.1)
    for _ in range(6):
        await _trace(db_session, rollout, quality=0.70)  # over the floor...
        await _trace(db_session, rollout, arm="incumbent", quality=0.95)  # ...but 0.25 worse

    await evaluate_prompt_rollouts(db_session)

    assert rollout.stage == "rolled_back"
    assert "incumbent" in (rollout.outcome_reason or "")


@pytest.mark.asyncio
async def test_a_deprecated_challenger_is_rolled_back_without_waiting_for_evidence(
    db_session: AsyncSession,
) -> None:
    rollout = await _rollout(db_session)
    challenger = (
        await db_session.execute(select(PromptVersion).where(PromptVersion.version == 2))
    ).scalar_one()
    challenger.status = "deprecated"
    await db_session.commit()

    await evaluate_prompt_rollouts(db_session)

    assert rollout.stage == "rolled_back"
    assert "deprecated" in (rollout.outcome_reason or "")


@pytest.mark.asyncio
async def test_only_this_applications_traffic_for_this_prompt_counts(
    db_session: AsyncSession,
) -> None:
    rollout = await _rollout(db_session)
    for _ in range(10):  # plenty of *errors*, but for other apps / other prompts
        await _trace(db_session, rollout, status="error", application_id="someone-else")
        await _trace(db_session, rollout, status="error", prompt_id="another-prompt")
    for _ in range(6):
        await _trace(db_session, rollout, quality=0.9)

    await evaluate_prompt_rollouts(db_session)

    assert rollout.stage == "running"
    assert rollout.traffic_pct == 20.0


@pytest.mark.asyncio
async def test_thin_windows_accumulate_across_passes(db_session: AsyncSession) -> None:
    rollout = await _rollout(db_session, min_sample_size=5)
    for _ in range(3):
        await _trace(db_session, rollout, quality=0.9)
    assert await evaluate_prompt_rollouts(db_session) == []

    for _ in range(3):
        await _trace(db_session, rollout, quality=0.9)
    changed = await evaluate_prompt_rollouts(db_session)

    assert len(changed) == 1
    assert "6 healthy challenger requests" in (changed[0].outcome_reason or "")


@pytest.mark.asyncio
async def test_paused_and_finished_rollouts_are_left_alone(db_session: AsyncSession) -> None:
    rollout = await _rollout(db_session, stage="paused")
    for _ in range(6):
        await _trace(db_session, rollout, status="error")

    assert await evaluate_prompt_rollouts(db_session) == []
    assert rollout.stage == "paused"
