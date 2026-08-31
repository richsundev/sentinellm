import pytest
from httpx import ASGITransport, AsyncClient

from sentinellm.api.main import create_app


@pytest.mark.asyncio
async def test_missing_api_key_is_rejected() -> None:
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as ac:
        resp = await ac.get("/api/v1/traces")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_invalid_api_key_is_rejected(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/traces", headers={"X-API-Key": "not-a-real-key"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_health_endpoint_requires_no_auth() -> None:
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as ac:
        resp = await ac.get("/health")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_read_role_cannot_write(client: AsyncClient, app) -> None:
    from sentinellm.api.deps import get_current_api_key

    class _ReadOnlyKey:
        role = "read"
        id = "fake"

    app.dependency_overrides[get_current_api_key] = lambda: _ReadOnlyKey()
    try:
        resp = await client.post(
            "/api/v1/traces",
            json={
                "application_id": "x",
                "model": "mock:sentinel-flash",
                "provider": "mock",
                "prompt": "q",
                "response": "a",
                "input_tokens": 1,
                "output_tokens": 1,
                "latency_ms": 1.0,
                "evaluate": False,
            },
        )
        assert resp.status_code == 403
    finally:
        del app.dependency_overrides[get_current_api_key]


@pytest.mark.asyncio
async def test_rate_limit_returns_429_after_threshold(client: AsyncClient) -> None:
    statuses = []
    for _ in range(30):
        resp = await client.get("/api/v1/models")
        statuses.append(resp.status_code)
    assert 429 in statuses
