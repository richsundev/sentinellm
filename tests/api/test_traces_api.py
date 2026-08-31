import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_ingest_and_fetch_trace(client: AsyncClient) -> None:
    payload = {
        "application_id": "support-bot",
        "model": "mock:sentinel-flash",
        "provider": "mock",
        "prompt": "What is the refund policy?",
        "response": "Refunds are honored within 30 days.",
        "input_tokens": 42,
        "output_tokens": 18,
        "latency_ms": 640.0,
        "evaluate": False,
    }
    create_resp = await client.post("/api/v1/traces", json=payload)
    assert create_resp.status_code == 201
    body = create_resp.json()
    assert body["application_id"] == "support-bot"
    assert body["estimated_cost"] > 0

    get_resp = await client.get(f"/api/v1/traces/{body['trace_id']}")
    assert get_resp.status_code == 200
    assert get_resp.json()["id"] == body["id"]


@pytest.mark.asyncio
async def test_duplicate_trace_ingestion_is_idempotent(client: AsyncClient) -> None:
    payload = {
        "trace_id": "trc_fixed_id_1",
        "application_id": "support-bot",
        "model": "mock:sentinel-flash",
        "provider": "mock",
        "prompt": "q",
        "response": "a",
        "input_tokens": 5,
        "output_tokens": 5,
        "latency_ms": 100.0,
        "evaluate": False,
    }
    first = await client.post("/api/v1/traces", json=payload)
    second = await client.post("/api/v1/traces", json=payload)

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["id"] == second.json()["id"]

    listing = await client.get("/api/v1/traces", params={"application_id": "support-bot"})
    matching = [t for t in listing.json()["items"] if t["trace_id"] == "trc_fixed_id_1"]
    assert len(matching) == 1


@pytest.mark.asyncio
async def test_list_traces_filters_by_model(client: AsyncClient) -> None:
    for model in ("mock:sentinel-flash", "mock:sentinel-pro"):
        await client.post(
            "/api/v1/traces",
            json={
                "application_id": "filter-app",
                "model": model,
                "provider": "mock",
                "prompt": "q",
                "response": "a",
                "input_tokens": 1,
                "output_tokens": 1,
                "latency_ms": 10.0,
                "evaluate": False,
            },
        )

    resp = await client.get(
        "/api/v1/traces", params={"application_id": "filter-app", "model": "mock:sentinel-pro"}
    )
    items = resp.json()["items"]
    assert all(item["model"] == "mock:sentinel-pro" for item in items)
    assert len(items) == 1


@pytest.mark.asyncio
async def test_get_unknown_trace_returns_404(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/traces/does-not-exist")
    assert resp.status_code == 404
