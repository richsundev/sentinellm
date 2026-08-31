import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_create_and_list_dataset_with_records(client: AsyncClient) -> None:
    payload = {
        "name": "support-eval",
        "version": "v1",
        "records": [
            {
                "question": "What is the refund window?",
                "context": "Refunds within 30 days.",
                "expected_answer": "30 days",
            },
            {
                "question": "Do you ship internationally?",
                "context": "We ship to over 40 countries.",
                "expected_answer": "Yes",
            },
        ],
    }
    create_resp = await client.post("/api/v1/datasets", json=payload)
    assert create_resp.status_code == 201
    dataset = create_resp.json()
    assert dataset["record_count"] == 2

    records_resp = await client.get(f"/api/v1/datasets/{dataset['id']}/records")
    assert records_resp.json()["total"] == 2


@pytest.mark.asyncio
async def test_prompt_versioning_increments_and_status_update(client: AsyncClient) -> None:
    v1 = await client.post(
        "/api/v1/prompts",
        json={
            "prompt_id": "support-answer",
            "template": "Answer: {{question}}",
            "variables": ["question"],
        },
    )
    v2 = await client.post(
        "/api/v1/prompts",
        json={
            "prompt_id": "support-answer",
            "template": "Answer concisely: {{question}}",
            "variables": ["question"],
        },
    )

    assert v1.json()["version"] == 1
    assert v2.json()["version"] == 2

    update_resp = await client.patch(
        "/api/v1/prompts/support-answer/versions/2", json={"status": "production"}
    )
    assert update_resp.json()["status"] == "production"

    listing = await client.get("/api/v1/prompts", params={"prompt_id": "support-answer"})
    assert listing.json()["total"] == 2


@pytest.mark.asyncio
async def test_list_experiments_empty_returns_page(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/experiments")
    assert resp.status_code == 200
    assert resp.json() == {"items": [], "total": 0, "limit": 25, "offset": 0}


@pytest.mark.asyncio
async def test_overview_metrics_empty_window(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/metrics/overview", params={"range": "1h"})
    assert resp.status_code == 200
    assert resp.json()["request_volume"] == 0
