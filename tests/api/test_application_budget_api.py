import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_create_application_with_budget(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/v1/applications",
        json={"name": "budgeted-app", "description": "demo", "daily_cost_budget": 5.0},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == "budgeted-app"
    assert body["daily_cost_budget"] == 5.0


@pytest.mark.asyncio
async def test_create_application_without_budget_defaults_to_none(client: AsyncClient) -> None:
    resp = await client.post("/api/v1/applications", json={"name": "unbudgeted-app"})
    assert resp.status_code == 201
    assert resp.json()["daily_cost_budget"] is None


@pytest.mark.asyncio
async def test_patch_application_sets_budget(client: AsyncClient) -> None:
    created = await client.post("/api/v1/applications", json={"name": "growing-app"})
    app_id = created.json()["id"]

    patched = await client.patch(f"/api/v1/applications/{app_id}", json={"daily_cost_budget": 25.0})
    assert patched.status_code == 200
    assert patched.json()["daily_cost_budget"] == 25.0
    assert patched.json()["description"] is None


@pytest.mark.asyncio
async def test_patch_unknown_application_returns_404(client: AsyncClient) -> None:
    resp = await client.patch(
        "/api/v1/applications/does-not-exist", json={"daily_cost_budget": 1.0}
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_create_application_rejects_negative_budget(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/v1/applications", json={"name": "bad-app", "daily_cost_budget": -1.0}
    )
    assert resp.status_code == 422
