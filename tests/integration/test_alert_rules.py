from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sentinellm.core.ids import new_trace_id
from sentinellm.db.models import AlertRuleConfig, Trace
from sentinellm.worker.tasks.alerting import ensure_default_alert_rules, evaluate_alert_rules


async def _make_error_trace(session: AsyncSession) -> None:
    session.add(
        Trace(
            trace_id=new_trace_id(),
            request_id="req",
            application_id="app-1",
            model="mock:sentinel-flash",
            provider="mock",
            prompt="q",
            response="a",
            status="error",
            latency_ms=100,
            estimated_cost=0.001,
            created_at=datetime.now(UTC),
        )
    )
    await session.commit()


@pytest.mark.asyncio
async def test_ensure_default_alert_rules_creates_five_rules(db_session: AsyncSession) -> None:
    created = await ensure_default_alert_rules(db_session)
    assert {r.rule for r in created} == {
        "error_rate",
        "p95_latency",
        "daily_cost",
        "quality_score",
        "hallucination_rate",
    }
    for rule in created:
        assert rule.enabled is True
        assert rule.threshold > 0


@pytest.mark.asyncio
async def test_ensure_default_alert_rules_is_idempotent(db_session: AsyncSession) -> None:
    await ensure_default_alert_rules(db_session)
    second_pass = await ensure_default_alert_rules(db_session)
    assert second_pass == []

    rows = (await db_session.execute(select(AlertRuleConfig))).scalars().all()
    assert len(rows) == 5


@pytest.mark.asyncio
async def test_ensure_default_alert_rules_never_overwrites_edited_threshold(
    db_session: AsyncSession,
) -> None:
    await ensure_default_alert_rules(db_session)
    row = (
        await db_session.execute(
            select(AlertRuleConfig).where(AlertRuleConfig.rule == "error_rate")
        )
    ).scalar_one()
    row.threshold = 0.99
    await db_session.commit()

    await ensure_default_alert_rules(db_session)

    refreshed = (
        await db_session.execute(
            select(AlertRuleConfig).where(AlertRuleConfig.rule == "error_rate")
        )
    ).scalar_one()
    assert refreshed.threshold == 0.99


@pytest.mark.asyncio
async def test_disabled_rule_never_fires(db_session: AsyncSession) -> None:
    await ensure_default_alert_rules(db_session)
    row = (
        await db_session.execute(
            select(AlertRuleConfig).where(AlertRuleConfig.rule == "error_rate")
        )
    ).scalar_one()
    row.enabled = False
    await db_session.commit()

    for _ in range(20):
        await _make_error_trace(db_session)

    alerts = await evaluate_alert_rules(db_session)
    assert not any(a.rule == "error_rate" for a in alerts)


@pytest.mark.asyncio
async def test_lowering_threshold_makes_rule_fire_sooner(db_session: AsyncSession) -> None:
    await ensure_default_alert_rules(db_session)
    row = (
        await db_session.execute(
            select(AlertRuleConfig).where(AlertRuleConfig.rule == "error_rate")
        )
    ).scalar_one()
    row.threshold = 0.01  # a single error trace should now be enough to breach it
    await db_session.commit()

    await _make_error_trace(db_session)
    for _ in range(9):
        session_trace = Trace(
            trace_id=new_trace_id(),
            request_id="req",
            application_id="app-1",
            model="mock:sentinel-flash",
            provider="mock",
            prompt="q",
            response="a",
            status="ok",
            latency_ms=100,
            estimated_cost=0.001,
            created_at=datetime.now(UTC),
        )
        db_session.add(session_trace)
    await db_session.commit()

    alerts = await evaluate_alert_rules(db_session)
    assert any(a.rule == "error_rate" for a in alerts)
