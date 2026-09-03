import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_create_model(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/v1/models",
        json={
            "id": "openai:gpt-4o-mini",
            "name": "gpt-4o-mini",
            "provider": "openai",
            "input_price_per_1k": 0.00015,
            "output_price_per_1k": 0.0006,
            "context_window": 128000,
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["id"] == "openai:gpt-4o-mini"
    assert body["status"] == "healthy"
    assert body["avg_quality"] is None  # no trace history yet

    listing = await client.get("/api/v1/models")
    assert any(m["id"] == "openai:gpt-4o-mini" for m in listing.json()["items"])


@pytest.mark.asyncio
async def test_create_duplicate_model_returns_409(client: AsyncClient) -> None:
    payload = {
        "id": "openai:gpt-4o",
        "name": "gpt-4o",
        "provider": "openai",
        "input_price_per_1k": 0.0025,
        "output_price_per_1k": 0.01,
    }
    first = await client.post("/api/v1/models", json=payload)
    assert first.status_code == 201
    second = await client.post("/api/v1/models", json=payload)
    assert second.status_code == 409


@pytest.mark.asyncio
async def test_update_model_partial_fields(client: AsyncClient) -> None:
    await client.post(
        "/api/v1/models",
        json={
            "id": "mock:test-model",
            "name": "test-model",
            "provider": "mock",
            "input_price_per_1k": 0.001,
            "output_price_per_1k": 0.002,
        },
    )

    resp = await client.patch("/api/v1/models/mock:test-model", json={"status": "degraded"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "degraded"
    assert resp.json()["input_price_per_1k"] == 0.001  # untouched

    resp2 = await client.patch("/api/v1/models/mock:test-model", json={"input_price_per_1k": 0.005})
    assert resp2.json()["input_price_per_1k"] == 0.005
    assert resp2.json()["status"] == "degraded"  # untouched by this call


@pytest.mark.asyncio
async def test_update_unknown_model_returns_404(client: AsyncClient) -> None:
    resp = await client.patch("/api/v1/models/does-not-exist", json={"status": "down"})
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_create_model_validates_negative_price(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/v1/models",
        json={
            "id": "bad:model",
            "name": "bad",
            "provider": "bad",
            "input_price_per_1k": -1.0,
            "output_price_per_1k": 0.001,
        },
    )
    assert resp.status_code == 422
