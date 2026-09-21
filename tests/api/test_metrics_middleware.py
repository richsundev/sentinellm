"""`sentinel_requests_total` feeds the SentinelHighErrorRate alert. An
unhandled exception (the *actual* 5xx) skipped the counting code entirely, and
unmatched/rate-limited paths were labelled with the raw URL — one new time
series per distinct path an attacker (or a typo) could produce."""

import pytest
from httpx import ASGITransport, AsyncClient
from prometheus_client import REGISTRY

from sentinellm.api.main import create_app


def _count(method: str, path: str, status: int) -> float:
    return (
        REGISTRY.get_sample_value(
            "sentinel_requests_total", {"method": method, "path": path, "status": str(status)}
        )
        or 0.0
    )


def _app_with_failing_route():
    app = create_app()

    @app.get("/test-only/boom")
    async def boom() -> None:
        raise RuntimeError("unhandled failure")

    return app


@pytest.mark.asyncio
async def test_unhandled_exceptions_are_counted_as_500s() -> None:
    app = _app_with_failing_route()
    before = _count("GET", "/test-only/boom", 500)

    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://t"
    ) as client:
        resp = await client.get("/test-only/boom")

    assert resp.status_code == 500
    assert _count("GET", "/test-only/boom", 500) == before + 1


@pytest.mark.asyncio
async def test_unmatched_paths_share_one_bounded_label() -> None:
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        for suffix in ("a1", "b2", "c3"):
            await client.get(f"/api/v1/does-not-exist/{suffix}")

    assert _count("GET", "unmatched", 404) >= 3
    for suffix in ("a1", "b2", "c3"):
        assert _count("GET", f"/api/v1/does-not-exist/{suffix}", 404) == 0


@pytest.mark.asyncio
async def test_routed_requests_keep_their_route_template_label(client: AsyncClient) -> None:
    before = _count("GET", "/api/v1/traces/{trace_id}", 404)

    await client.get("/api/v1/traces/trc_does_not_exist")

    assert _count("GET", "/api/v1/traces/{trace_id}", 404) == before + 1
