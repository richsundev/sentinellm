from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from sentinellm.core.ids import new_trace_id
from sentinellm.db.models import ModelPricing, Trace
from sentinellm.worker.tasks.model_health import evaluate_model_health


async def _make_trace(db_session: AsyncSession, *, model: str, status: str) -> None:
    trace = Trace(
        trace_id=new_trace_id(),
        request_id="req",
        application_id="app-1",
        model=model,
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
    await db_session.commit()


async def _make_model(db_session: AsyncSession, model_id: str, **kwargs: object) -> ModelPricing:
    row = ModelPricing(id=model_id, name=model_id, provider="mock", **kwargs)
    db_session.add(row)
    await db_session.commit()
    return row


@pytest.mark.asyncio
async def test_high_error_rate_flips_model_to_down(db_session: AsyncSession) -> None:
    await _make_model(db_session, "mock:flaky")
    for _ in range(10):
        await _make_trace(db_session, model="mock:flaky", status="error")

    changed = await evaluate_model_health(db_session)
    assert any(m.id == "mock:flaky" and m.status == "down" for m in changed)


@pytest.mark.asyncio
async def test_moderate_error_rate_flips_model_to_degraded(db_session: AsyncSession) -> None:
    await _make_model(db_session, "mock:shaky")
    # 3 errors / 10 = 30% -> degraded, not down.
    for _ in range(7):
        await _make_trace(db_session, model="mock:shaky", status="ok")
    for _ in range(3):
        await _make_trace(db_session, model="mock:shaky", status="error")

    changed = await evaluate_model_health(db_session)
    row = next(m for m in changed if m.id == "mock:shaky")
    assert row.status == "degraded"
    assert "error rate" in (row.status_reason or "")


@pytest.mark.asyncio
async def test_healthy_traffic_stays_healthy(db_session: AsyncSession) -> None:
    await _make_model(db_session, "mock:solid")
    for _ in range(10):
        await _make_trace(db_session, model="mock:solid", status="ok")

    changed = await evaluate_model_health(db_session)
    row = next(m for m in changed if m.id == "mock:solid")
    assert row.status == "healthy"

    # A second pass with the same traffic is a true no-op: status and
    # reason both already match, nothing to persist.
    second_pass = await evaluate_model_health(db_session)
    assert second_pass == []


@pytest.mark.asyncio
async def test_manually_pinned_model_is_never_auto_managed(db_session: AsyncSession) -> None:
    await _make_model(db_session, "mock:pinned", status="healthy", status_auto=False)
    for _ in range(10):
        await _make_trace(db_session, model="mock:pinned", status="error")

    changed = await evaluate_model_health(db_session)
    assert changed == []


@pytest.mark.asyncio
async def test_below_min_sample_is_not_evaluated(db_session: AsyncSession) -> None:
    await _make_model(db_session, "mock:new")
    for _ in range(3):
        await _make_trace(db_session, model="mock:new", status="error")

    changed = await evaluate_model_health(db_session)
    assert changed == []
