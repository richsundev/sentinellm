import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession


async def _create_rollout(
    client: AsyncClient,
    *,
    application_id: str = "rollout-app",
    incumbent_model: str = "mock:sentinel-nano",
    challenger_model: str = "mock:sentinel-pro",
    **overrides: object,
) -> dict:
    payload = {
        "application_id": application_id,
        "incumbent_model": incumbent_model,
        "challenger_model": challenger_model,
        **overrides,
    }
    resp = await client.post("/api/v1/rollouts", json=payload)
    return resp


@pytest.mark.asyncio
async def test_create_rollout_starts_at_initial_pct(
    client: AsyncClient, seeded_models: AsyncSession
) -> None:
    resp = await _create_rollout(client, initial_pct=15.0)
    assert resp.status_code == 201
    body = resp.json()
    assert body["traffic_pct"] == 15.0
    assert body["stage"] == "running"
    assert body["incumbent_model"] == "mock:sentinel-nano"
    assert body["challenger_model"] == "mock:sentinel-pro"


@pytest.mark.asyncio
async def test_create_rollout_rejects_same_model_for_both_arms(
    client: AsyncClient, seeded_models: AsyncSession
) -> None:
    resp = await _create_rollout(client, challenger_model="mock:sentinel-nano")
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_create_rollout_conflicts_with_existing_active_rollout(
    client: AsyncClient, seeded_models: AsyncSession
) -> None:
    first = await _create_rollout(client)
    assert first.status_code == 201

    second = await _create_rollout(client)
    assert second.status_code == 409


@pytest.mark.asyncio
async def test_creating_new_rollout_after_rollback_succeeds(
    client: AsyncClient, seeded_models: AsyncSession
) -> None:
    first = await _create_rollout(client)
    rollout_id = first.json()["id"]
    await client.post(f"/api/v1/rollouts/{rollout_id}/rollback")

    second = await _create_rollout(client)
    assert second.status_code == 201


@pytest.mark.asyncio
async def test_pause_resume_lifecycle(client: AsyncClient, seeded_models: AsyncSession) -> None:
    created = await _create_rollout(client)
    rollout_id = created.json()["id"]

    paused = await client.post(f"/api/v1/rollouts/{rollout_id}/pause")
    assert paused.status_code == 200
    assert paused.json()["stage"] == "paused"

    cant_pause_again = await client.post(f"/api/v1/rollouts/{rollout_id}/pause")
    assert cant_pause_again.status_code == 400

    resumed = await client.post(f"/api/v1/rollouts/{rollout_id}/resume")
    assert resumed.status_code == 200
    assert resumed.json()["stage"] == "running"


@pytest.mark.asyncio
async def test_manual_promote_sets_full_traffic(
    client: AsyncClient, seeded_models: AsyncSession
) -> None:
    created = await _create_rollout(client, initial_pct=10.0, max_pct=100.0)
    rollout_id = created.json()["id"]

    promoted = await client.post(f"/api/v1/rollouts/{rollout_id}/promote")
    assert promoted.status_code == 200
    body = promoted.json()
    assert body["stage"] == "promoted"
    assert body["traffic_pct"] == 100.0

    cant_promote_again = await client.post(f"/api/v1/rollouts/{rollout_id}/promote")
    assert cant_promote_again.status_code == 400


@pytest.mark.asyncio
async def test_manual_rollback_zeroes_traffic(
    client: AsyncClient, seeded_models: AsyncSession
) -> None:
    created = await _create_rollout(client, initial_pct=50.0)
    rollout_id = created.json()["id"]

    rolled_back = await client.post(f"/api/v1/rollouts/{rollout_id}/rollback")
    assert rolled_back.status_code == 200
    body = rolled_back.json()
    assert body["stage"] == "rolled_back"
    assert body["traffic_pct"] == 0.0


@pytest.mark.asyncio
async def test_get_rollout_detail_includes_arm_stats(
    client: AsyncClient, seeded_models: AsyncSession
) -> None:
    created = await _create_rollout(client)
    rollout_id = created.json()["id"]

    detail = await client.get(f"/api/v1/rollouts/{rollout_id}")
    assert detail.status_code == 200
    body = detail.json()
    assert body["incumbent_stats"]["model"] == "mock:sentinel-nano"
    assert body["challenger_stats"]["model"] == "mock:sentinel-pro"
    assert body["incumbent_stats"]["request_count"] == 0


@pytest.mark.asyncio
async def test_get_rollout_detail_reflects_real_traffic(
    client: AsyncClient, seeded_models: AsyncSession
) -> None:
    created = await _create_rollout(client, initial_pct=100.0)
    rollout_id = created.json()["id"]

    for _ in range(3):
        await client.post(
            "/api/v1/generate",
            json={
                "application_id": "rollout-app",
                "question": "hi",
                "use_cache": False,
                "evaluate": False,
            },
        )

    detail = await client.get(f"/api/v1/rollouts/{rollout_id}")
    body = detail.json()
    assert body["challenger_stats"]["request_count"] == 3
    assert body["challenger_stats"]["error_rate"] == 0.0
    assert body["incumbent_stats"]["request_count"] == 0


@pytest.mark.asyncio
async def test_get_unknown_rollout_returns_404(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/rollouts/does-not-exist")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_list_rollouts_filters_by_application_and_stage(
    client: AsyncClient, seeded_models: AsyncSession
) -> None:
    a = await _create_rollout(client, application_id="app-a")
    await _create_rollout(client, application_id="app-b")
    await client.post(f"/api/v1/rollouts/{a.json()['id']}/rollback")

    only_a = await client.get("/api/v1/rollouts", params={"application_id": "app-a"})
    assert only_a.json()["total"] == 1

    only_running = await client.get("/api/v1/rollouts", params={"stage": "running"})
    stages = {r["stage"] for r in only_running.json()["items"]}
    assert stages == {"running"}
