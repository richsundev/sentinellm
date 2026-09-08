from collections import Counter

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession


async def _create_rollout(client: AsyncClient, **overrides: object) -> dict:
    payload = {
        "application_id": "split-app",
        "incumbent_model": "mock:sentinel-nano",
        "challenger_model": "mock:sentinel-pro",
        "initial_pct": 50.0,
        **overrides,
    }
    resp = await client.post("/api/v1/rollouts", json=payload)
    assert resp.status_code == 201
    return resp.json()


@pytest.mark.asyncio
async def test_unpinned_requests_split_traffic_by_rollout_pct(
    client: AsyncClient, seeded_models: AsyncSession
) -> None:
    rollout = await _create_rollout(client, initial_pct=50.0)

    # Kept comfortably under the test suite's SENTINEL_RATE_LIMIT_PER_MINUTE
    # (20, see conftest.py) — the moving-window limiter is a shared
    # in-memory singleton keyed by this test's one API key, so every call
    # in this test counts against the same budget. 15 draws at p=0.5 still
    # makes an all-one-arm split astronomically unlikely (~2 * 0.5**15).
    models_seen: Counter[str] = Counter()
    for _ in range(15):
        resp = await client.post(
            "/api/v1/generate",
            json={
                "application_id": "split-app",
                "question": "what is your refund policy",
                "use_cache": False,
                "evaluate": False,
            },
        )
        models_seen[resp.json()["model"]] += 1

    assert set(models_seen) <= {"mock:sentinel-nano", "mock:sentinel-pro"}
    # Statistical, not exact: with 40 draws at p=0.5 both arms should show
    # up; a 0/40 or 40/0 split would indicate the split logic is broken.
    assert models_seen["mock:sentinel-nano"] > 0
    assert models_seen["mock:sentinel-pro"] > 0
    assert rollout["traffic_pct"] == 50.0


@pytest.mark.asyncio
async def test_explicit_preferred_model_bypasses_active_rollout(
    client: AsyncClient, seeded_models: AsyncSession
) -> None:
    await _create_rollout(client, initial_pct=100.0)

    resp = await client.post(
        "/api/v1/generate",
        json={
            "application_id": "split-app",
            "question": "hello",
            "preferred_model": "mock:sentinel-opus",
            "use_cache": False,
            "evaluate": False,
        },
    )
    assert resp.json()["model"] == "mock:sentinel-opus"


@pytest.mark.asyncio
async def test_trace_metadata_records_rollout_arm(
    client: AsyncClient, seeded_models: AsyncSession
) -> None:
    rollout = await _create_rollout(client, initial_pct=100.0)

    resp = await client.post(
        "/api/v1/generate",
        json={
            "application_id": "split-app",
            "question": "hello",
            "use_cache": False,
            "evaluate": False,
        },
    )
    body = resp.json()
    assert body["model"] == "mock:sentinel-pro"
    assert body["metadata"]["rollout_id"] == rollout["id"]
    assert body["metadata"]["rollout_arm"] == "challenger"


@pytest.mark.asyncio
async def test_zero_pct_rollout_always_routes_incumbent(
    client: AsyncClient, seeded_models: AsyncSession
) -> None:
    await _create_rollout(client, initial_pct=0.0)

    for _ in range(5):
        resp = await client.post(
            "/api/v1/generate",
            json={
                "application_id": "split-app",
                "question": "hello",
                "use_cache": False,
                "evaluate": False,
            },
        )
        assert resp.json()["model"] == "mock:sentinel-nano"


@pytest.mark.asyncio
async def test_promoted_rollout_keeps_routing_challenger(
    client: AsyncClient, seeded_models: AsyncSession
) -> None:
    rollout = await _create_rollout(client, initial_pct=10.0)
    await client.post(f"/api/v1/rollouts/{rollout['id']}/promote")

    resp = await client.post(
        "/api/v1/generate",
        json={
            "application_id": "split-app",
            "question": "hello",
            "use_cache": False,
            "evaluate": False,
        },
    )
    assert resp.json()["model"] == "mock:sentinel-pro"


@pytest.mark.asyncio
async def test_rolled_back_rollout_keeps_routing_incumbent(
    client: AsyncClient, seeded_models: AsyncSession
) -> None:
    rollout = await _create_rollout(client, initial_pct=90.0)
    await client.post(f"/api/v1/rollouts/{rollout['id']}/rollback")

    resp = await client.post(
        "/api/v1/generate",
        json={
            "application_id": "split-app",
            "question": "hello",
            "use_cache": False,
            "evaluate": False,
        },
    )
    assert resp.json()["model"] == "mock:sentinel-nano"
