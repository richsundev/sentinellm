"""The dashboards' numbers must not depend on how much traffic there is.
`cost_summary` summed an arbitrary 5,000 rows (silently under-reporting spend
on a busy system); `overview` kept the *oldest* 5,000 of a window, so the
'last 24h' view described the start of the day; and per-model quality was
divided by every trace though only evaluated ones contribute."""

from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from sentinellm.api.routers import metrics as metrics_router
from sentinellm.core.ids import new_trace_id
from sentinellm.db.models import Evaluation, Trace


async def _add(
    session: AsyncSession,
    *,
    model: str = "mock:a",
    app: str = "app-1",
    cost: float = 1.0,
    status: str = "ok",
    age: timedelta = timedelta(minutes=5),
    quality: float | None = None,
) -> None:
    trace = Trace(
        trace_id=new_trace_id(),
        request_id="r",
        application_id=app,
        model=model,
        provider="mock",
        prompt="q",
        response="a",
        status=status,
        latency_ms=100.0,
        estimated_cost=cost,
        evaluation_status="skipped",
        created_at=datetime.now(UTC) - age,
    )
    session.add(trace)
    await session.flush()
    if quality is not None:
        session.add(Evaluation(trace_id=trace.id, overall_quality=quality, hallucination_score=0.0))
    await session.commit()


@pytest.mark.asyncio
async def test_cost_totals_are_exact_beyond_the_sample_cap(
    client: AsyncClient, db_session: AsyncSession, monkeypatch
) -> None:
    monkeypatch.setattr(metrics_router, "_SAMPLE_CAP", 3)
    for i in range(10):
        await _add(db_session, model="mock:a" if i % 2 else "mock:b", app=f"app-{i % 2}", cost=1.0)

    body = (await client.get("/api/v1/metrics/cost", params={"range": "30d"})).json()

    assert body["total_cost"] == pytest.approx(10.0)
    assert sum(m["cost"] for m in body["by_model"]) == pytest.approx(10.0)
    assert sum(a["cost"] for a in body["by_application"]) == pytest.approx(10.0)
    assert sum(d["cost"] for d in body["daily"]) == pytest.approx(10.0)


@pytest.mark.asyncio
async def test_cost_breakdowns_group_and_sort_correctly(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    for _ in range(3):
        await _add(db_session, model="mock:big", app="app-x", cost=2.0)
    await _add(db_session, model="mock:small", app="app-y", cost=0.5)

    body = (await client.get("/api/v1/metrics/cost", params={"range": "30d"})).json()

    assert [m["model"] for m in body["by_model"]] == ["mock:big", "mock:small"]
    assert body["by_model"][0]["cost"] == pytest.approx(6.0)
    assert {a["application_id"]: a["cost"] for a in body["by_application"]} == pytest.approx(
        {"app-x": 6.0, "app-y": 0.5}
    )
    today = datetime.now(UTC).date().isoformat()
    assert body["daily"] == [{"date": today, "cost": pytest.approx(6.5)}]


@pytest.mark.asyncio
async def test_cost_summary_of_an_empty_window_is_zero(client: AsyncClient) -> None:
    body = (await client.get("/api/v1/metrics/cost")).json()
    assert body["total_cost"] == 0.0
    assert body["daily"] == body["by_model"] == body["by_application"] == []


@pytest.mark.asyncio
async def test_cost_insight_averages_quality_over_evaluated_traces_only(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """`cheap` has 4 traces but only 2 evaluated (both 0.90); summing 1.80 over
    4 gave 0.45 — making it look far worse than the pricier model and hiding
    the 'cheaper, similar quality' insight."""
    for _ in range(4):
        await _add(db_session, model="mock:pricey", cost=0.10, quality=0.90)
    await _add(db_session, model="mock:cheap", cost=0.01, quality=0.90)
    await _add(db_session, model="mock:cheap", cost=0.01, quality=0.90)
    await _add(db_session, model="mock:cheap", cost=0.01)
    await _add(db_session, model="mock:cheap", cost=0.01)

    body = (await client.get("/api/v1/metrics/cost", params={"range": "30d"})).json()

    assert body["insight_text"] is not None
    assert "mock:cheap" in body["insight_text"]
    assert "0.90 vs 0.90" in body["insight_text"]


@pytest.mark.asyncio
async def test_overview_request_volume_is_exact_beyond_the_sample_cap(
    client: AsyncClient, db_session: AsyncSession, monkeypatch
) -> None:
    monkeypatch.setattr(metrics_router, "_SAMPLE_CAP", 3)
    for _ in range(10):
        await _add(db_session)

    body = (await client.get("/api/v1/metrics/overview", params={"range": "24h"})).json()

    assert body["request_volume"] == 10


@pytest.mark.asyncio
async def test_overview_samples_the_newest_traffic_not_the_oldest(
    client: AsyncClient, db_session: AsyncSession, monkeypatch
) -> None:
    """Older traffic was all errors, the newest is healthy; with the sample
    capped, the 'last 24h' error rate must describe *now*."""
    monkeypatch.setattr(metrics_router, "_SAMPLE_CAP", 3)
    for hours in range(10, 3, -1):
        await _add(db_session, status="error", age=timedelta(hours=hours))
    for minutes in (3, 2, 1):
        await _add(db_session, status="ok", age=timedelta(minutes=minutes))

    body = (await client.get("/api/v1/metrics/overview", params={"range": "24h"})).json()

    assert body["error_rate"] == 0.0
    assert body["request_volume"] == 10
