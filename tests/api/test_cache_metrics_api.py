import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.mark.asyncio
async def test_overview_reports_zero_cache_stats_when_no_traffic(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/metrics/overview", params={"range": "24h"})
    body = resp.json()
    assert body["cache_hit_count"] == 0
    assert body["cache_hit_rate"] == 0.0
    assert body["estimated_cache_savings"] == 0.0


@pytest.mark.asyncio
async def test_overview_computes_cache_hit_rate_and_savings(
    client: AsyncClient, seeded_models: AsyncSession
) -> None:
    payload = {
        "application_id": "cache-metrics-app",
        "question": "What is your refund policy for annual plans?",
        "preferred_model": "mock:sentinel-flash",
        "use_cache": True,
        "evaluate": False,
    }
    first = await client.post("/api/v1/generate", json=payload)
    second = await client.post("/api/v1/generate", json=payload)
    assert first.json()["cache_hit"] is False
    assert second.json()["cache_hit"] is True

    overview = await client.get("/api/v1/metrics/overview", params={"range": "24h"})
    body = overview.json()
    assert body["cache_hit_count"] == 1
    assert body["cache_hit_rate"] == 0.5
    # One cache hit, estimated against the one real (non-hit) request's cost.
    assert body["estimated_cache_savings"] == pytest.approx(
        first.json()["estimated_cost"], abs=1e-6
    )
