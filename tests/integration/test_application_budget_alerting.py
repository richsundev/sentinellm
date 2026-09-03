from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from sentinellm.core.ids import new_trace_id
from sentinellm.db.models import Application, Trace
from sentinellm.worker.tasks.alerting import evaluate_alert_rules


async def _make_trace(db_session: AsyncSession, *, application_id: str, cost: float) -> None:
    trace = Trace(
        trace_id=new_trace_id(),
        request_id="req",
        application_id=application_id,
        model="mock:sentinel-flash",
        provider="mock",
        prompt="q",
        response="a",
        status="ok",
        latency_ms=100.0,
        estimated_cost=cost,
        evaluation_status="pending",
        created_at=datetime.now(UTC),
    )
    db_session.add(trace)
    await db_session.commit()


@pytest.mark.asyncio
async def test_application_over_budget_fires_alert(db_session: AsyncSession) -> None:
    app = Application(name="pricey-app", daily_cost_budget=1.0)
    db_session.add(app)
    await db_session.commit()

    for _ in range(5):
        await _make_trace(db_session, application_id=app.id, cost=0.5)

    alerts = await evaluate_alert_rules(db_session)
    app_alerts = [a for a in alerts if a.rule == "app_cost_budget"]
    assert len(app_alerts) == 1
    assert app_alerts[0].affected_service == "app:pricey-app"
    assert app_alerts[0].current_value == pytest.approx(2.5)
    assert app_alerts[0].threshold == 1.0


@pytest.mark.asyncio
async def test_application_under_budget_fires_no_alert(db_session: AsyncSession) -> None:
    app = Application(name="frugal-app", daily_cost_budget=100.0)
    db_session.add(app)
    await db_session.commit()

    await _make_trace(db_session, application_id=app.id, cost=0.5)

    alerts = await evaluate_alert_rules(db_session)
    assert not any(a.rule == "app_cost_budget" for a in alerts)


@pytest.mark.asyncio
async def test_application_without_budget_is_never_checked(db_session: AsyncSession) -> None:
    app = Application(name="unbudgeted-app")
    db_session.add(app)
    await db_session.commit()

    for _ in range(5):
        await _make_trace(db_session, application_id=app.id, cost=10.0)

    alerts = await evaluate_alert_rules(db_session)
    assert not any(a.rule == "app_cost_budget" for a in alerts)


@pytest.mark.asyncio
async def test_application_budget_alert_deduplicated_within_window(
    db_session: AsyncSession,
) -> None:
    app = Application(name="pricey-app-2", daily_cost_budget=1.0)
    db_session.add(app)
    await db_session.commit()

    for _ in range(5):
        await _make_trace(db_session, application_id=app.id, cost=0.5)

    first = await evaluate_alert_rules(db_session)
    second = await evaluate_alert_rules(db_session)

    assert any(a.rule == "app_cost_budget" for a in first)
    assert not any(a.rule == "app_cost_budget" for a in second)
