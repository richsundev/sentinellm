import pytest
from httpx import AsyncClient


async def _ingest_trace(client: AsyncClient, *, prompt: str = "q", response: str = "a") -> str:
    resp = await client.post(
        "/api/v1/traces",
        json={
            "application_id": "tagging-app",
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
async def test_new_trace_has_no_tags(client: AsyncClient) -> None:
    trace_id = await _ingest_trace(client)
    resp = await client.get(f"/api/v1/traces/{trace_id}")
    assert resp.json()["tags"] == []


@pytest.mark.asyncio
async def test_set_trace_tags_normalizes_and_dedupes(client: AsyncClient) -> None:
    trace_id = await _ingest_trace(client)
    resp = await client.patch(
        f"/api/v1/traces/{trace_id}/tags", json={"tags": ["PII", " escalation ", "pii"]}
    )
    assert resp.status_code == 200
    assert resp.json() == {"trace_id": trace_id, "tags": ["escalation", "pii"]}

    fetched = await client.get(f"/api/v1/traces/{trace_id}")
    assert fetched.json()["tags"] == ["escalation", "pii"]


@pytest.mark.asyncio
async def test_set_trace_tags_replaces_not_merges(client: AsyncClient) -> None:
    trace_id = await _ingest_trace(client)
    await client.patch(f"/api/v1/traces/{trace_id}/tags", json={"tags": ["needs-review"]})
    second = await client.patch(f"/api/v1/traces/{trace_id}/tags", json={"tags": ["escalation"]})
    assert second.json()["tags"] == ["escalation"]


@pytest.mark.asyncio
async def test_set_tags_on_unknown_trace_returns_404(client: AsyncClient) -> None:
    resp = await client.patch("/api/v1/traces/does-not-exist/tags", json={"tags": ["x"]})
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_list_traces_filters_by_tag(client: AsyncClient) -> None:
    tagged = await _ingest_trace(client, prompt="tagged one")
    untagged = await _ingest_trace(client, prompt="untagged one")
    await client.patch(f"/api/v1/traces/{tagged}/tags", json={"tags": ["escalation"]})

    resp = await client.get("/api/v1/traces", params={"tag": "escalation"})
    body = resp.json()
    ids = {t["trace_id"] for t in body["items"]}
    assert tagged in ids
    assert untagged not in ids
