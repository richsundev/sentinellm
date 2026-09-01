import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_import_dataset_from_jsonl(client: AsyncClient) -> None:
    content = (
        b'{"question": "What is the refund window?", "context": "30 days", "expected_answer": "30 days"}\n'
        b'{"question": "Do you ship internationally?", "context": "Yes", "expected_answer": "Yes"}\n'
    )
    resp = await client.post(
        "/api/v1/datasets/import",
        data={"name": "imported-jsonl", "version": "v1"},
        files={"file": ("bench.jsonl", content, "application/x-ndjson")},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == "imported-jsonl"
    assert body["record_count"] == 2

    records = await client.get(f"/api/v1/datasets/{body['id']}/records")
    assert records.json()["total"] == 2


@pytest.mark.asyncio
async def test_import_dataset_from_csv(client: AsyncClient) -> None:
    content = b"question,context,expected_answer\nQ1?,C1,A1\nQ2?,C2,A2\n"
    resp = await client.post(
        "/api/v1/datasets/import",
        data={"name": "imported-csv", "version": "v1", "description": "from csv"},
        files={"file": ("bench.csv", content, "text/csv")},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["record_count"] == 2
    assert body["description"] == "from csv"


@pytest.mark.asyncio
async def test_import_dataset_rejects_unsupported_extension(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/v1/datasets/import",
        data={"name": "bad", "version": "v1"},
        files={"file": ("bench.txt", b"question\nQ1?\n", "text/plain")},
    )
    assert resp.status_code == 400
    assert "unsupported file type" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_import_dataset_rejects_malformed_jsonl(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/v1/datasets/import",
        data={"name": "bad", "version": "v1"},
        files={"file": ("bench.jsonl", b"not json at all\n", "application/x-ndjson")},
    )
    assert resp.status_code == 400
    assert "line 1" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_import_dataset_rejects_empty_file(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/v1/datasets/import",
        data={"name": "bad", "version": "v1"},
        files={"file": ("bench.jsonl", b"\n\n", "application/x-ndjson")},
    )
    assert resp.status_code == 400
