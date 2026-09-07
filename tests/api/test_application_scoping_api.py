"""A scoped API key (`scoped_to_application=True`) should only ever see or
write its own application's traces/metrics/applications/keys — everything
else in this file exercises that boundary. The default (unscoped) key used
by every other test file must keep seeing everything, which the existing
full suite passing already covers; this file is additive.
"""

import pytest
from httpx import ASGITransport, AsyncClient


async def _create_scoped_client(
    admin_client: AsyncClient, app, application_name: str
) -> tuple[AsyncClient, str]:
    app_resp = await admin_client.post("/api/v1/applications", json={"name": application_name})
    app_id = app_resp.json()["id"]

    key_resp = await admin_client.post(
        "/api/v1/applications/api-keys",
        json={
            "application_id": app_id,
            "name": "scoped-key",
            "role": "admin",
            "scoped_to_application": True,
        },
    )
    assert key_resp.json()["scoped_to_application"] is True
    plaintext = key_resp.json()["plaintext_key"]

    return AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
        headers={"X-API-Key": plaintext},
    ), app_id


async def _ingest_trace(client: AsyncClient, *, application_id: str, prompt: str = "q") -> str:
    resp = await client.post(
        "/api/v1/traces",
        json={
            "application_id": application_id,
            "model": "mock:sentinel-flash",
            "provider": "mock",
            "prompt": prompt,
            "response": "a",
            "input_tokens": 1,
            "output_tokens": 1,
            "latency_ms": 1.0,
            "evaluate": False,
        },
    )
    return resp


@pytest.mark.asyncio
async def test_scoped_key_can_ingest_for_its_own_application(client: AsyncClient, app) -> None:
    scoped, app_id = await _create_scoped_client(client, app, "scoped-app-1")
    async with scoped:
        resp = await _ingest_trace(scoped, application_id=app_id)
        assert resp.status_code == 201


@pytest.mark.asyncio
async def test_scoped_key_cannot_ingest_for_another_application(client: AsyncClient, app) -> None:
    scoped, _app_id = await _create_scoped_client(client, app, "scoped-app-2")
    async with scoped:
        resp = await _ingest_trace(scoped, application_id="some-other-app")
        assert resp.status_code == 403


@pytest.mark.asyncio
async def test_scoped_key_list_traces_excludes_other_applications(client: AsyncClient, app) -> None:
    scoped, app_id = await _create_scoped_client(client, app, "scoped-app-3")
    async with scoped:
        await _ingest_trace(scoped, application_id=app_id, prompt="mine")
        await _ingest_trace(client, application_id="unrelated-app", prompt="not mine")

        resp = await scoped.get("/api/v1/traces", params={"limit": 50})
        prompts = {t["prompt"] for t in resp.json()["items"]}
        assert "mine" in prompts
        assert "not mine" not in prompts


@pytest.mark.asyncio
async def test_scoped_key_get_trace_404s_for_other_applications(client: AsyncClient, app) -> None:
    scoped, _app_id = await _create_scoped_client(client, app, "scoped-app-4")
    foreign = await _ingest_trace(client, application_id="foreign-app")
    foreign_trace_id = foreign.json()["trace_id"]

    async with scoped:
        resp = await scoped.get(f"/api/v1/traces/{foreign_trace_id}")
        assert resp.status_code == 404


@pytest.mark.asyncio
async def test_scoped_key_feedback_and_tags_404_for_other_applications(
    client: AsyncClient, app
) -> None:
    scoped, _app_id = await _create_scoped_client(client, app, "scoped-app-5")
    foreign = await _ingest_trace(client, application_id="foreign-app-2")
    foreign_trace_id = foreign.json()["trace_id"]

    async with scoped:
        feedback_resp = await scoped.post(
            f"/api/v1/traces/{foreign_trace_id}/feedback", json={"rating": "up"}
        )
        assert feedback_resp.status_code == 404

        tags_resp = await scoped.patch(
            f"/api/v1/traces/{foreign_trace_id}/tags", json={"tags": ["x"]}
        )
        assert tags_resp.status_code == 404


@pytest.mark.asyncio
async def test_scoped_key_overview_metrics_excludes_other_applications(
    client: AsyncClient, app
) -> None:
    scoped, app_id = await _create_scoped_client(client, app, "scoped-app-6")
    async with scoped:
        await _ingest_trace(scoped, application_id=app_id)
        await _ingest_trace(client, application_id="unrelated-app-2")

        resp = await scoped.get("/api/v1/metrics/overview", params={"range": "24h"})
        assert resp.json()["request_volume"] == 1


@pytest.mark.asyncio
async def test_scoped_key_lists_only_its_own_application(client: AsyncClient, app) -> None:
    scoped, app_id = await _create_scoped_client(client, app, "scoped-app-7")
    async with scoped:
        resp = await scoped.get("/api/v1/applications")
        body = resp.json()
        assert body["total"] == 1
        assert body["items"][0]["id"] == app_id


@pytest.mark.asyncio
async def test_scoped_key_cannot_create_new_application(client: AsyncClient, app) -> None:
    scoped, _app_id = await _create_scoped_client(client, app, "scoped-app-8")
    async with scoped:
        resp = await scoped.post("/api/v1/applications", json={"name": "sibling-app"})
        assert resp.status_code == 403


@pytest.mark.asyncio
async def test_scoped_key_cannot_create_key_for_another_application(
    client: AsyncClient, app
) -> None:
    scoped, _app_id = await _create_scoped_client(client, app, "scoped-app-9")
    async with scoped:
        resp = await scoped.post(
            "/api/v1/applications/api-keys",
            json={"application_id": "some-other-app", "name": "sneaky"},
        )
        assert resp.status_code == 403


@pytest.mark.asyncio
async def test_unscoped_key_default_behavior_is_unrestricted(client: AsyncClient) -> None:
    # scoped_to_application defaults to False, so a normally-created key
    # (as every other test file uses) keeps seeing everything.
    resp = await _ingest_trace(client, application_id="anything-goes")
    assert resp.status_code == 201
