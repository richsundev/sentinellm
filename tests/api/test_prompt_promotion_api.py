import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession


async def _seed_dataset(client: AsyncClient, name: str = "promo-bench") -> str:
    resp = await client.post(
        "/api/v1/datasets",
        json={
            "name": name,
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
        },
    )
    return resp.json()["id"]


@pytest.mark.asyncio
async def test_promote_without_experiment_returns_400(
    client: AsyncClient, seeded_models: AsyncSession
) -> None:
    await _seed_dataset(client)
    await client.post(
        "/api/v1/prompts", json={"prompt_id": "promo-prompt", "template": "Q: {{question}}"}
    )

    resp = await client.post("/api/v1/prompts/promo-prompt/versions/1/promote", json={})
    assert resp.status_code == 400
    assert "no experiment found" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_promote_with_low_pass_rate_returns_400(
    client: AsyncClient, seeded_models: AsyncSession
) -> None:
    dataset_id = await _seed_dataset(client)
    await client.post(
        "/api/v1/prompts", json={"prompt_id": "promo-prompt-2", "template": "Q: {{question}}"}
    )

    # A quality_pass_threshold of 1.0 on the run guarantees the resulting
    # experiment's pass_rate is essentially never 1.0 against the mock
    # provider's non-perfect deterministic scoring — used here to force a
    # low-pass-rate experiment deterministically rather than asserting on
    # whatever score happens to come out.
    await client.post(
        "/api/v1/experiments/run",
        json={
            "name": "low-bar-run",
            "model": "mock:sentinel-nano",
            "prompt_id": "promo-prompt-2",
            "prompt_version": 1,
            "dataset_id": dataset_id,
            "quality_pass_threshold": 1.0,
        },
    )

    resp = await client.post(
        "/api/v1/prompts/promo-prompt-2/versions/1/promote", json={"quality_pass_threshold": 1.0}
    )
    assert resp.status_code == 400
    assert "below the" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_promote_with_passing_experiment_succeeds_and_demotes_previous(
    client: AsyncClient, seeded_models: AsyncSession
) -> None:
    dataset_id = await _seed_dataset(client)
    v1 = await client.post(
        "/api/v1/prompts",
        json={"prompt_id": "promo-prompt-3", "template": "Q: {{question}}", "status": "production"},
    )
    assert v1.json()["version"] == 1
    v2 = await client.post(
        "/api/v1/prompts", json={"prompt_id": "promo-prompt-3", "template": "Answer: {{question}}"}
    )
    assert v2.json()["version"] == 2

    await client.post(
        "/api/v1/experiments/run",
        json={
            "name": "v2-run",
            "model": "mock:sentinel-pro",
            "prompt_id": "promo-prompt-3",
            "prompt_version": 2,
            "dataset_id": dataset_id,
            "quality_pass_threshold": 0.0,
        },
    )

    resp = await client.post(
        "/api/v1/prompts/promo-prompt-3/versions/2/promote", json={"quality_pass_threshold": 0.0}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["promoted"]["status"] == "production"
    assert body["promoted"]["version"] == 2
    assert body["demoted_version"] == 1
    assert body["justifying_experiment_id"]

    listing = await client.get("/api/v1/prompts", params={"prompt_id": "promo-prompt-3"})
    statuses = {item["version"]: item["status"] for item in listing.json()["items"]}
    assert statuses == {1: "deprecated", 2: "production"}


@pytest.mark.asyncio
async def test_promote_unknown_prompt_version_returns_404(client: AsyncClient) -> None:
    resp = await client.post("/api/v1/prompts/does-not-exist/versions/1/promote", json={})
    assert resp.status_code == 404
