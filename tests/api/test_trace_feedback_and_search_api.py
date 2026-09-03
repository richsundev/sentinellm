import pytest
from httpx import AsyncClient


async def _ingest_trace(
    client: AsyncClient, *, prompt: str, response: str, application_id: str = "app-1"
) -> str:
    resp = await client.post(
        "/api/v1/traces",
        json={
            "application_id": application_id,
            "model": "mock:sentinel-flash",
            "provider": "mock",
            "prompt": prompt,
            "response": response,
            "input_tokens": 5,
            "output_tokens": 5,
            "latency_ms": 10.0,
            "evaluate": False,
        },
    )
    return resp.json()["trace_id"]


@pytest.mark.asyncio
async def test_submit_feedback_creates_then_updates(client: AsyncClient) -> None:
    trace_id = await _ingest_trace(client, prompt="q", response="a")

    first = await client.post(
        f"/api/v1/traces/{trace_id}/feedback", json={"rating": "up", "note": "good"}
    )
    assert first.status_code == 200
    assert first.json() == {
        "trace_id": trace_id,
        "rating": "up",
        "note": "good",
        "created_at": first.json()["created_at"],
    }

    second = await client.post(
        f"/api/v1/traces/{trace_id}/feedback", json={"rating": "down", "note": "actually no"}
    )
    assert second.json()["rating"] == "down"
    assert second.json()["note"] == "actually no"

    trace = await client.get(f"/api/v1/traces/{trace_id}")
    assert trace.json()["feedback"] == {
        "trace_id": trace_id,
        "rating": "down",
        "note": "actually no",
        "created_at": second.json()["created_at"],
    }


@pytest.mark.asyncio
async def test_submit_feedback_unknown_trace_returns_404(client: AsyncClient) -> None:
    resp = await client.post("/api/v1/traces/does-not-exist/feedback", json={"rating": "up"})
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_submit_feedback_rejects_invalid_rating(client: AsyncClient) -> None:
    trace_id = await _ingest_trace(client, prompt="q", response="a")
    resp = await client.post(f"/api/v1/traces/{trace_id}/feedback", json={"rating": "sideways"})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_trace_search_matches_prompt_and_response(client: AsyncClient) -> None:
    await _ingest_trace(
        client,
        prompt="What is the refund window?",
        response="Thirty days.",
        application_id="search-app",
    )
    await _ingest_trace(
        client,
        prompt="Do you ship internationally?",
        response="Yes, 40 countries.",
        application_id="search-app",
    )

    by_prompt = await client.get(
        "/api/v1/traces", params={"application_id": "search-app", "q": "refund"}
    )
    assert by_prompt.json()["total"] == 1
    assert "refund" in by_prompt.json()["items"][0]["prompt"].lower()

    by_response = await client.get(
        "/api/v1/traces", params={"application_id": "search-app", "q": "countries"}
    )
    assert by_response.json()["total"] == 1

    case_insensitive = await client.get(
        "/api/v1/traces", params={"application_id": "search-app", "q": "REFUND"}
    )
    assert case_insensitive.json()["total"] == 1

    no_match = await client.get(
        "/api/v1/traces", params={"application_id": "search-app", "q": "nonexistent-term"}
    )
    assert no_match.json()["total"] == 0
