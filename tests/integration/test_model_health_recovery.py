"""A model flagged down is excluded from routing, so it stops earning the
traffic that could clear it — health also has to be able to *recover*, and to
see failures that a successful fallback hid."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from sentinellm.core.ids import new_trace_id
from sentinellm.db.models import ModelPricing, Trace
from sentinellm.worker.tasks.model_health import evaluate_model_health


async def _model(session: AsyncSession, model_id: str, **kwargs: object) -> ModelPricing:
    row = ModelPricing(id=model_id, name=model_id, provider="mock", **kwargs)
    session.add(row)
    await session.commit()
    return row


async def _trace(
    session: AsyncSession,
    model: str,
    *,
    status: str = "ok",
    cache_hit: bool = False,
    failed_attempts: list[dict] | None = None,
    age_minutes: float = 1,
) -> None:
    session.add(
        Trace(
            trace_id=new_trace_id(),
            request_id="req",
            application_id="app-1",
            model=model,
            provider="mock",
            prompt="q",
            response="a",
            status=status,
            cache_hit=cache_hit,
            trace_metadata={"failed_attempts": failed_attempts} if failed_attempts else {},
            created_at=datetime.now(UTC) - timedelta(minutes=age_minutes),
        )
    )
    await session.commit()


@pytest.mark.asyncio
async def test_a_down_model_with_no_recent_evidence_is_given_another_chance(
    db_session: AsyncSession,
) -> None:
    row = await _model(
        db_session, "mock:was-down", status="down", status_reason="error rate 100% over last 10"
    )
    # Its failures are long outside the health window, and nothing has been
    # routed to it since (it's excluded).
    for _ in range(10):
        await _trace(db_session, "mock:was-down", status="error", age_minutes=180)

    await evaluate_model_health(db_session)

    await db_session.refresh(row)
    assert row.status == "degraded"  # routable again, so fresh traffic can decide
    assert "retry" in (row.status_reason or "")


@pytest.mark.asyncio
async def test_a_down_model_stays_down_while_its_failures_are_recent(
    db_session: AsyncSession,
) -> None:
    row = await _model(db_session, "mock:still-down", status="down")
    for _ in range(10):
        await _trace(db_session, "mock:still-down", status="error", age_minutes=5)

    await evaluate_model_health(db_session)

    await db_session.refresh(row)
    assert row.status == "down"


@pytest.mark.asyncio
async def test_an_operators_manual_down_is_never_recovered_automatically(
    db_session: AsyncSession,
) -> None:
    row = await _model(db_session, "mock:pinned", status="down", status_auto=False)

    await evaluate_model_health(db_session)
    await _trace(db_session, "mock:other")  # any traffic at all, so the pass runs
    await evaluate_model_health(db_session)

    await db_session.refresh(row)
    assert row.status == "down"


@pytest.mark.asyncio
async def test_failures_hidden_by_a_successful_fallback_still_count_against_the_model(
    db_session: AsyncSession,
) -> None:
    """Every request served by the fallback looks like a success for the
    fallback — the primary failing 100% of the time was invisible, so it kept
    being tried first (paying retries and backoff) forever."""
    flaky = await _model(db_session, "mock:flaky-primary")
    await _model(db_session, "mock:fallback")
    for _ in range(10):
        await _trace(
            db_session,
            "mock:fallback",
            failed_attempts=[{"model": "mock:flaky-primary", "error_kind": "timeout"}],
        )

    await evaluate_model_health(db_session)

    await db_session.refresh(flaky)
    assert flaky.status == "down"
    assert "error rate" in (flaky.status_reason or "")


@pytest.mark.asyncio
async def test_cache_hits_do_not_dilute_a_models_error_rate(db_session: AsyncSession) -> None:
    """A cache hit never called the model, so it says nothing about its health."""
    row = await _model(db_session, "mock:cached")
    for _ in range(6):
        await _trace(db_session, "mock:cached", status="error")
    for _ in range(30):
        await _trace(db_session, "mock:cached", cache_hit=True)

    await evaluate_model_health(db_session)

    await db_session.refresh(row)
    assert row.status == "down"
