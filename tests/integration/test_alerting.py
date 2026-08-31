from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from sentinellm.core.ids import new_trace_id
from sentinellm.db.models import Evaluation, Trace
from sentinellm.worker.tasks.alerting import evaluate_alert_rules


async def _make_trace(
    db_session: AsyncSession,
    *,
    status: str,
    latency_ms: float,
    cost: float,
    quality: float | None,
    hallucination: float | None,
) -> None:
    trace = Trace(
        trace_id=new_trace_id(),
        request_id="req",
        application_id="app-1",
        model="mock:sentinel-flash",
        provider="mock",
        prompt="q",
        response="a",
        status=status,
        latency_ms=latency_ms,
        estimated_cost=cost,
        evaluation_status="completed" if quality is not None else "pending",
        created_at=datetime.now(UTC),
    )
    db_session.add(trace)
    await db_session.flush()
    if quality is not None:
        db_session.add(
            Evaluation(
                trace_id=trace.id, overall_quality=quality, hallucination_score=hallucination or 0.0
            )
        )
    await db_session.commit()


@pytest.mark.asyncio
async def test_high_error_rate_fires_alert(db_session: AsyncSession) -> None:
    for _ in range(20):
        await _make_trace(
            db_session, status="error", latency_ms=100, cost=0.001, quality=None, hallucination=None
        )

    alerts = await evaluate_alert_rules(db_session)
    rules_fired = {a.rule for a in alerts}
    assert "error_rate" in rules_fired


@pytest.mark.asyncio
async def test_high_hallucination_rate_fires_alert(db_session: AsyncSession) -> None:
    for _ in range(20):
        await _make_trace(
            db_session, status="ok", latency_ms=200, cost=0.001, quality=0.7, hallucination=0.5
        )

    alerts = await evaluate_alert_rules(db_session)
    rules_fired = {a.rule for a in alerts}
    assert "hallucination_rate" in rules_fired
    assert "quality_score" in rules_fired


@pytest.mark.asyncio
async def test_healthy_traffic_fires_no_alerts(db_session: AsyncSession) -> None:
    for _ in range(20):
        await _make_trace(
            db_session, status="ok", latency_ms=300, cost=0.0005, quality=0.95, hallucination=0.02
        )

    alerts = await evaluate_alert_rules(db_session)
    assert alerts == []


@pytest.mark.asyncio
async def test_alert_deduplicated_within_window(db_session: AsyncSession) -> None:
    for _ in range(20):
        await _make_trace(
            db_session, status="error", latency_ms=100, cost=0.001, quality=None, hallucination=None
        )

    first = await evaluate_alert_rules(db_session)
    second = await evaluate_alert_rules(db_session)

    assert any(a.rule == "error_rate" for a in first)
    assert not any(a.rule == "error_rate" for a in second)
