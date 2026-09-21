"""A daily budget used to be an alert and nothing more: an application could sail
past it. `budget_action` lets it hold the line — `downgrade` to the cheapest
healthy model, or `block` with a 402 — checked at admission on the trailing-24h
spend."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from sentinellm.core.config import get_settings
from sentinellm.core.ids import new_trace_id
from sentinellm.db.models import Application, Trace
from sentinellm.services.budget import reset_budget_cache

_PRO = "mock:sentinel-pro"
_NANO = "mock:sentinel-nano"


async def _app(client: AsyncClient, name: str, **over: object) -> dict:
    resp = await client.post("/api/v1/applications", json={"name": name, **over})
    assert resp.status_code == 201, resp.text
    return resp.json()


def _gen(app_name: str, **over: object) -> dict:
    return {
        "application_id": app_name,
        "question": "What is the refund policy?",
        "preferred_model": _PRO,
        "use_cache": False,
        "evaluate": False,
        **over,
    }


async def _spend(session: AsyncSession, application_id: str, cost: float, age=timedelta(0)) -> None:
    session.add(
        Trace(
            trace_id=new_trace_id(),
            request_id="r",
            application_id=application_id,
            model=_PRO,
            provider="mock",
            prompt="q",
            response="a",
            estimated_cost=cost,
            created_at=datetime.now(UTC) - age,
        )
    )
    await session.commit()


@pytest.fixture(autouse=True)
def _fresh_budget_cache() -> None:
    reset_budget_cache()


@pytest.mark.asyncio
async def test_block_refuses_requests_once_the_budget_is_spent(
    client: AsyncClient, seeded_models: AsyncSession
) -> None:
    await _app(client, "blocked-app", daily_cost_budget=1e-7, budget_action="block")

    first = await client.post("/api/v1/generate", json=_gen("blocked-app"))
    assert first.status_code == 200  # nothing spent yet
    assert first.json()["estimated_cost"] > 1e-7  # ...and that request alone used it up

    second = await client.post("/api/v1/generate", json=_gen("blocked-app"))

    assert second.status_code == 402
    detail = second.json()["detail"]
    assert "budget" in detail
    assert "$1e-07" in detail  # a tiny budget isn't rounded to "$0.0000"
    assert second.headers["X-Budget-Action"] == "block"


@pytest.mark.asyncio
async def test_block_only_looks_at_the_last_24_hours(
    client: AsyncClient, seeded_models: AsyncSession
) -> None:
    await _app(client, "yesterday-app", daily_cost_budget=1.0, budget_action="block")
    await _spend(seeded_models, "yesterday-app", 50.0, age=timedelta(hours=30))
    assert (await client.post("/api/v1/generate", json=_gen("yesterday-app"))).status_code == 200

    await _spend(seeded_models, "yesterday-app", 1.5)
    assert (await client.post("/api/v1/generate", json=_gen("yesterday-app"))).status_code == 402


@pytest.mark.asyncio
async def test_spend_recorded_under_the_applications_id_counts_too(
    client: AsyncClient, seeded_models: AsyncSession
) -> None:
    """`Trace.application_id` is the row's id or its name, depending on the caller."""
    created = await _app(client, "by-id-app", daily_cost_budget=1.0, budget_action="block")
    await _spend(seeded_models, created["id"], 2.0)

    assert (await client.post("/api/v1/generate", json=_gen("by-id-app"))).status_code == 402
    assert (await client.post("/api/v1/generate", json=_gen(created["id"]))).status_code == 402


@pytest.mark.asyncio
async def test_alert_only_and_unbudgeted_applications_are_never_stopped(
    client: AsyncClient, seeded_models: AsyncSession
) -> None:
    await _app(client, "alert-only", daily_cost_budget=0.0001)  # action defaults to alert
    await _spend(seeded_models, "alert-only", 5.0)
    await _app(client, "no-budget", budget_action="block")  # nothing to enforce
    await _spend(seeded_models, "no-budget", 5.0)

    assert (await client.post("/api/v1/generate", json=_gen("alert-only"))).status_code == 200
    assert (await client.post("/api/v1/generate", json=_gen("no-budget"))).status_code == 200
    assert (await client.post("/api/v1/generate", json=_gen("unregistered"))).status_code == 200


@pytest.mark.asyncio
async def test_downgrade_serves_the_cheapest_healthy_model_and_says_so(
    client: AsyncClient, seeded_models: AsyncSession
) -> None:
    await _app(client, "downgrade-app", daily_cost_budget=1.0, budget_action="downgrade")

    before = (await client.post("/api/v1/generate", json=_gen("downgrade-app"))).json()
    assert before["model"] == _PRO
    assert "budget_downgrade" not in before["metadata"]

    await _spend(seeded_models, "downgrade-app", 5.0)
    after = (await client.post("/api/v1/generate", json=_gen("downgrade-app"))).json()

    assert after["status"] == "ok"
    assert after["model"] == _NANO
    assert after["metadata"]["budget_downgrade"]["to"] == _NANO
    assert after["metadata"]["budget_downgrade"]["budget"] == 1.0


@pytest.mark.asyncio
async def test_downgrade_also_replaces_router_and_canary_choices(
    client: AsyncClient, seeded_models: AsyncSession
) -> None:
    await _app(client, "routed-app", daily_cost_budget=1.0, budget_action="downgrade")
    await _spend(seeded_models, "routed-app", 5.0)
    await client.post(
        "/api/v1/rollouts",
        json={
            "application_id": "routed-app",
            "incumbent_model": _PRO,
            "challenger_model": "mock:sentinel-opus",
            "initial_pct": 100,
        },
    )

    body = _gen("routed-app")
    del body["preferred_model"]
    trace = (await client.post("/api/v1/generate", json=body)).json()

    assert trace["model"] == _NANO  # not the 100% canary arm (opus), not the router's pick
    assert "rollout_id" not in trace["metadata"]


@pytest.mark.asyncio
async def test_downgrade_never_moves_a_request_to_a_dearer_model(
    client: AsyncClient, seeded_models: AsyncSession
) -> None:
    await _app(client, "cheap-app", daily_cost_budget=1.0, budget_action="downgrade")
    await _spend(seeded_models, "cheap-app", 5.0)

    trace = (
        await client.post("/api/v1/generate", json=_gen("cheap-app", preferred_model=_NANO))
    ).json()

    assert trace["model"] == _NANO
    assert "budget_downgrade" not in trace["metadata"]


@pytest.mark.asyncio
async def test_a_replay_is_not_a_way_around_the_budget(
    client: AsyncClient, seeded_models: AsyncSession
) -> None:
    await _app(client, "replay-app", daily_cost_budget=1.0, budget_action="block")
    original = (await client.post("/api/v1/generate", json=_gen("replay-app"))).json()
    await _spend(seeded_models, "replay-app", 5.0)

    resp = await client.post(f"/api/v1/traces/{original['trace_id']}/replay", json={})

    assert resp.status_code == 402


@pytest.mark.asyncio
async def test_the_budget_status_endpoint_reports_live_numbers(
    client: AsyncClient, seeded_models: AsyncSession
) -> None:
    created = await _app(client, "status-app", daily_cost_budget=10.0, budget_action="block")
    await _spend(seeded_models, "status-app", 2.5)
    await _spend(seeded_models, created["id"], 1.0)
    await _spend(seeded_models, "status-app", 99.0, age=timedelta(days=2))

    resp = await client.get(f"/api/v1/applications/{created['id']}/budget")

    assert resp.status_code == 200
    assert resp.json() == {
        "application_id": created["id"],
        "daily_cost_budget": 10.0,
        "budget_action": "block",
        "spent_24h": pytest.approx(3.5),
        "remaining": pytest.approx(6.5),
        "exceeded": False,
    }
    await _spend(seeded_models, "status-app", 7.0)
    assert (await client.get(f"/api/v1/applications/{created['id']}/budget")).json()["exceeded"]


@pytest.mark.asyncio
async def test_budget_status_of_an_unbudgeted_or_unknown_application(client: AsyncClient) -> None:
    created = await _app(client, "free-app")

    body = (await client.get(f"/api/v1/applications/{created['id']}/budget")).json()
    assert body["daily_cost_budget"] is None and body["remaining"] is None
    assert body["exceeded"] is False

    assert (await client.get("/api/v1/applications/nope/budget")).status_code == 404


@pytest.mark.asyncio
async def test_the_action_is_validated_and_editable(client: AsyncClient) -> None:
    bad = await client.post("/api/v1/applications", json={"name": "x", "budget_action": "explode"})
    assert bad.status_code == 422

    created = await _app(client, "editable", daily_cost_budget=5.0)
    assert created["budget_action"] == "alert"
    patched = await client.patch(
        f"/api/v1/applications/{created['id']}", json={"budget_action": "block"}
    )
    assert patched.json()["budget_action"] == "block"
    assert (
        await client.patch(f"/api/v1/applications/{created['id']}", json={"budget_action": "nope"})
    ).status_code == 422


@pytest.mark.asyncio
async def test_a_scoped_key_cannot_read_another_applications_budget(
    app, client: AsyncClient
) -> None:
    from httpx import ASGITransport

    mine = await _app(client, "mine-b")
    theirs = await _app(client, "theirs-b", daily_cost_budget=5.0)
    key = (
        await client.post(
            "/api/v1/applications/api-keys",
            json={"application_id": mine["id"], "role": "read", "scoped_to_application": True},
        )
    ).json()["plaintext_key"]

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://t", headers={"X-API-Key": key}
    ) as scoped:
        assert (await scoped.get(f"/api/v1/applications/{mine['id']}/budget")).status_code == 200
        assert (await scoped.get(f"/api/v1/applications/{theirs['id']}/budget")).status_code == 404


@pytest.mark.asyncio
async def test_enforcement_reads_are_cached_briefly(
    client: AsyncClient, seeded_models: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The check runs on every `/generate`; re-summing a day of traces each time
    would be a heavy tax. Within the TTL the answer is reused (enforcement is
    approximate by design), and it catches up as soon as it expires."""
    monkeypatch.setattr(get_settings(), "budget_cache_seconds", 60)
    await _app(client, "cached-app", daily_cost_budget=1.0, budget_action="block")
    assert (await client.post("/api/v1/generate", json=_gen("cached-app"))).status_code == 200

    await _spend(seeded_models, "cached-app", 50.0)
    assert (await client.post("/api/v1/generate", json=_gen("cached-app"))).status_code == 200

    reset_budget_cache()  # the TTL elapsing
    assert (await client.post("/api/v1/generate", json=_gen("cached-app"))).status_code == 402


async def test_budget_columns_exist_on_the_model(db_session: AsyncSession) -> None:
    row = Application(name="cols")
    db_session.add(row)
    await db_session.commit()
    assert row.budget_action == "alert"
