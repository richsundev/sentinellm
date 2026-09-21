"""Platform-level hardening: readiness, request size, and the dev-only webhook
receiver."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from sentinellm.api.deps import get_db
from sentinellm.api.main import create_app
from sentinellm.core.config import get_settings


@pytest.mark.asyncio
async def test_readiness_reports_the_database(client: AsyncClient) -> None:
    assert (await client.get("/ready")).json() == {"status": "ready"}


@pytest.mark.asyncio
async def test_readiness_fails_when_the_database_is_unreachable(app) -> None:
    class _Broken:
        async def execute(self, *_a: object, **_k: object) -> None:
            raise ConnectionError("db down")

    async def broken_db():
        yield _Broken()

    app.dependency_overrides[get_db] = broken_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as anon:
        health = await anon.get("/health")
        ready = await anon.get("/ready")

    assert health.status_code == 200  # liveness must not depend on the database
    assert ready.status_code == 503


@pytest.mark.asyncio
async def test_oversized_request_bodies_are_refused(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "max_request_bytes", 1_000)

    resp = await client.post(
        "/api/v1/traces",
        content=b"x" * 5_000,
        headers={"Content-Type": "application/json"},
    )

    assert resp.status_code == 413


@pytest.mark.asyncio
async def test_the_mock_webhook_receiver_is_not_mounted_in_production(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """It is unauthenticated and logs whatever it is sent."""
    monkeypatch.setattr(get_settings(), "env", "production")
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as anon:
        resp = await anon.post("/api/v1/_mock_webhook", json={"a": 1})
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_the_mock_webhook_receiver_still_works_locally(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    resp = await client.post("/api/v1/_mock_webhook", json={"a": 1})
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_dataset_import_never_reads_more_than_its_limit_into_memory(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The 5MB check used to run *after* `await file.read()` had loaded the
    whole upload."""
    from starlette.datastructures import UploadFile

    sizes: list[int] = []
    original = UploadFile.read

    async def spy(self: UploadFile, size: int = -1) -> bytes:
        sizes.append(size)
        return await original(self, size)

    monkeypatch.setattr(UploadFile, "read", spy)

    resp = await client.post(
        "/api/v1/datasets/import",
        data={"name": "d", "version": "1"},
        files={"file": ("d.jsonl", b'{"question": "q"}\n', "application/x-ndjson")},
    )

    assert resp.status_code == 201
    assert sizes and all(0 < s <= 5 * 1024 * 1024 + 1 for s in sizes)
