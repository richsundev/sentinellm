import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.mark.asyncio
async def test_replay_creates_new_trace_referencing_original(
    client: AsyncClient, seeded_models: AsyncSession
) -> None:
    original_resp = await client.post(
        "/api/v1/generate",
        json={
            "application_id": "replay-app",
            "question": "What is your refund policy?",
            "preferred_model": "mock:sentinel-pro",
            "use_cache": False,
            "evaluate": False,
        },
    )
    original = original_resp.json()

    replay_resp = await client.post(f"/api/v1/traces/{original['trace_id']}/replay", json={})
    assert replay_resp.status_code == 201
    replayed = replay_resp.json()

    assert replayed["trace_id"] != original["trace_id"]
    assert replayed["application_id"] == original["application_id"]
    assert replayed["prompt"] == original["prompt"]
    assert replayed["metadata"]["replay_of"] == original["trace_id"]


@pytest.mark.asyncio
async def test_replay_can_override_model(client: AsyncClient, seeded_models: AsyncSession) -> None:
    original_resp = await client.post(
        "/api/v1/generate",
        json={
            "application_id": "replay-app",
            "question": "What is your refund policy?",
            "preferred_model": "mock:sentinel-nano",
            "use_cache": False,
            "evaluate": False,
        },
    )
    original = original_resp.json()

    replay_resp = await client.post(
        f"/api/v1/traces/{original['trace_id']}/replay",
        json={"model": "mock:sentinel-pro"},
    )
    assert replay_resp.status_code == 201
    assert replay_resp.json()["model"] == "mock:sentinel-pro"
    assert original["model"] == "mock:sentinel-nano"


@pytest.mark.asyncio
async def test_replay_unknown_trace_returns_404(client: AsyncClient) -> None:
    resp = await client.post("/api/v1/traces/does-not-exist/replay", json={})
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_replay_preserves_retrieved_documents(
    client: AsyncClient, seeded_models: AsyncSession
) -> None:
    ingested = await client.post(
        "/api/v1/traces",
        json={
            "application_id": "replay-app",
            "model": "mock:sentinel-pro",
            "provider": "mock",
            "prompt": "What docs support this?",
            "response": "answer",
            "retrieved_documents": [
                {"doc_id": "d1", "content": "some context", "score": 0.9, "rank": 1}
            ],
            "evaluate": False,
        },
    )
    trace_id = ingested.json()["trace_id"]

    replay_resp = await client.post(f"/api/v1/traces/{trace_id}/replay", json={})
    assert replay_resp.status_code == 201
    replayed_docs = replay_resp.json()["retrieved_documents"]
    assert len(replayed_docs) == 1
    assert replayed_docs[0]["doc_id"] == "d1"
