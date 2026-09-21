"""`NoHealthyCandidateError` is documented as a first-class outcome
(docs/design-decisions.md #8) but nothing handled it: an unroutable request
surfaced as an unhandled 500."""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

_QUESTION = {"application_id": "route-app", "question": "hello", "use_cache": False}


@pytest.mark.asyncio
async def test_generate_returns_503_when_every_model_is_down(
    client: AsyncClient, seeded_models: AsyncSession
) -> None:
    models = (await client.get("/api/v1/models")).json()["items"]
    for m in models:
        await client.patch(f"/api/v1/models/{m['id']}", json={"status": "down"})

    resp = await client.post("/api/v1/generate", json=_QUESTION)

    assert resp.status_code == 503
    assert "no model" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_generate_returns_503_when_no_models_are_registered(client: AsyncClient) -> None:
    resp = await client.post("/api/v1/generate", json=_QUESTION)
    assert resp.status_code == 503


@pytest.mark.asyncio
async def test_an_explicit_preferred_model_still_works_when_routing_is_impossible(
    client: AsyncClient, seeded_models: AsyncSession
) -> None:
    for m in (await client.get("/api/v1/models")).json()["items"]:
        await client.patch(f"/api/v1/models/{m['id']}", json={"status": "down"})

    resp = await client.post(
        "/api/v1/generate", json={**_QUESTION, "preferred_model": "mock:sentinel-flash"}
    )

    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_replay_of_an_unroutable_trace_is_also_a_503(
    client: AsyncClient, seeded_models: AsyncSession
) -> None:
    original = await client.post(
        "/api/v1/generate", json={**_QUESTION, "preferred_model": "mock:sentinel-flash"}
    )
    for m in (await client.get("/api/v1/models")).json()["items"]:
        await client.patch(f"/api/v1/models/{m['id']}", json={"status": "down"})

    resp = await client.post(f"/api/v1/traces/{original.json()['trace_id']}/replay", json={})

    assert resp.status_code == 503
