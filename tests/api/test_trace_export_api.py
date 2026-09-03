import csv
import io

import pytest
from httpx import AsyncClient


async def _ingest_trace(
    client: AsyncClient, *, prompt: str, application_id: str = "export-app"
) -> str:
    resp = await client.post(
        "/api/v1/traces",
        json={
            "application_id": application_id,
            "model": "mock:sentinel-flash",
            "provider": "mock",
            "prompt": prompt,
            "response": "an answer",
            "input_tokens": 5,
            "output_tokens": 5,
            "latency_ms": 10.0,
            "estimated_cost": 0.002,
            "evaluate": False,
        },
    )
    return resp.json()["trace_id"]


@pytest.mark.asyncio
async def test_export_returns_csv_with_header_and_rows(client: AsyncClient) -> None:
    trace_id = await _ingest_trace(client, prompt="exportable question")

    resp = await client.get("/api/v1/traces/export")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")
    assert "attachment" in resp.headers["content-disposition"]

    rows = list(csv.reader(io.StringIO(resp.text)))
    header, *data_rows = rows
    assert header[0] == "trace_id"
    assert any(row[0] == trace_id for row in data_rows)


@pytest.mark.asyncio
async def test_export_honors_filters(client: AsyncClient) -> None:
    await _ingest_trace(client, prompt="alpha", application_id="app-alpha")
    await _ingest_trace(client, prompt="beta", application_id="app-beta")

    resp = await client.get("/api/v1/traces/export", params={"application_id": "app-alpha"})
    rows = list(csv.reader(io.StringIO(resp.text)))
    _, *data_rows = rows
    application_ids = {row[2] for row in data_rows}
    assert application_ids == {"app-alpha"}


@pytest.mark.asyncio
async def test_export_includes_tags_column(client: AsyncClient) -> None:
    trace_id = await _ingest_trace(client, prompt="tag me")
    await client.patch(f"/api/v1/traces/{trace_id}/tags", json={"tags": ["escalation", "pii"]})

    resp = await client.get("/api/v1/traces/export")
    rows = list(csv.reader(io.StringIO(resp.text)))
    header, *data_rows = rows
    tags_idx = header.index("tags")
    row = next(r for r in data_rows if r[0] == trace_id)
    assert row[tags_idx] == "escalation;pii"


@pytest.mark.asyncio
async def test_export_empty_result_is_header_only(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/traces/export", params={"application_id": "no-such-app"})
    rows = list(csv.reader(io.StringIO(resp.text)))
    assert len(rows) == 1
