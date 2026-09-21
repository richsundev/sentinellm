"""`daily_cost` and every application's `daily_cost_budget` were compared with
the spend of the trailing *hour* — a $50/day budget only alerted past $50 in a
single hour, i.e. about $1,200 a day."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from sentinellm.core.ids import new_trace_id
from sentinellm.db.models import Application, Trace
from sentinellm.worker.tasks.alerting import evaluate_alert_rules


async def _trace(
    db: AsyncSession, application_id: str, cost: float, age: timedelta = timedelta(0)
) -> None:
    db.add(
        Trace(
            trace_id=new_trace_id(),
            request_id="r",
            application_id=application_id,
            model="mock:sentinel-flash",
            provider="mock",
            prompt="q",
            response="a",
            latency_ms=10.0,
            estimated_cost=cost,
            created_at=datetime.now(UTC) - age,
        )
    )
    await db.commit()


@pytest.mark.asyncio
async def test_an_apps_spend_across_the_day_counts_against_its_daily_budget(
    db_session: AsyncSession,
) -> None:
    app = Application(name="spread-out", daily_cost_budget=10.0)
    db_session.add(app)
    await db_session.commit()
    # $1 every two hours for ~a day: nothing in any single hour is alarming, but
    # the day's spend is $12.
    for hours in range(0, 24, 2):
        await _trace(db_session, app.id, 1.0, timedelta(hours=hours, minutes=5))

    alerts = await evaluate_alert_rules(db_session)

    fired = [a for a in alerts if a.rule == "app_cost_budget"]
    assert len(fired) == 1
    assert fired[0].current_value == pytest.approx(12.0)


@pytest.mark.asyncio
async def test_spend_older_than_a_day_does_not_count(db_session: AsyncSession) -> None:
    app = Application(name="old-spend", daily_cost_budget=10.0)
    db_session.add(app)
    await db_session.commit()
    await _trace(db_session, app.id, 50.0, timedelta(hours=30))
    await _trace(db_session, app.id, 1.0)

    alerts = await evaluate_alert_rules(db_session)

    assert not [a for a in alerts if a.rule == "app_cost_budget"]


@pytest.mark.asyncio
async def test_the_global_daily_cost_rule_uses_the_day_too(db_session: AsyncSession) -> None:
    for hours in range(0, 24, 3):
        await _trace(db_session, "any-app", 10.0, timedelta(hours=hours, minutes=5))
    # default `daily_cost_budget` is $50; the day's spend is $80

    alerts = await evaluate_alert_rules(db_session)

    fired = [a for a in alerts if a.rule == "daily_cost"]
    assert len(fired) == 1
    assert fired[0].current_value == pytest.approx(80.0)


@pytest.mark.asyncio
async def test_a_quiet_last_hour_does_not_hide_an_overspent_day(db_session: AsyncSession) -> None:
    """The whole evaluation used to return early when the last hour had no
    traffic at all."""
    app = Application(name="went-quiet", daily_cost_budget=1.0)
    db_session.add(app)
    await db_session.commit()
    await _trace(db_session, app.id, 5.0, timedelta(hours=6))

    alerts = await evaluate_alert_rules(db_session)

    assert [a.rule for a in alerts if a.rule == "app_cost_budget"] == ["app_cost_budget"]
