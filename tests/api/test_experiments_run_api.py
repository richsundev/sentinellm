import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession


async def _seed_dataset_and_prompt(client: AsyncClient) -> tuple[str, str]:
    dataset_resp = await client.post(
        "/api/v1/datasets",
        json={
            "name": "experiment-bench",
            "version": "v1",
            "records": [
                {
                    "question": "What is the refund window?",
                    "context": "Refunds within 30 days of purchase.",
                    "expected_answer": "30 days",
                },
                {
                    "question": "Do you ship internationally?",
                    "context": "We ship to over 40 countries.",
                    "expected_answer": "Yes",
                },
                {
                    "question": "Is there a mobile app?",
                    "context": "Native iOS and Android apps are available.",
                    "expected_answer": "Yes",
                },
            ],
        },
    )
    dataset_id = dataset_resp.json()["id"]

    prompt_resp = await client.post(
        "/api/v1/prompts",
        json={
            "prompt_id": "exp-prompt",
            "template": "Answer using the context.\nContext: {{context}}\nQuestion: {{question}}",
            "variables": ["context", "question"],
        },
    )
    return dataset_id, prompt_resp.json()["prompt_id"]


@pytest.mark.asyncio
async def test_run_experiment_end_to_end(client: AsyncClient, seeded_models: AsyncSession) -> None:
    dataset_id, prompt_id = await _seed_dataset_and_prompt(client)

    resp = await client.post(
        "/api/v1/experiments/run",
        json={
            "name": "flash-v1-run",
            "model": "mock:sentinel-flash",
            "prompt_id": prompt_id,
            "prompt_version": 1,
            "dataset_id": dataset_id,
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == "flash-v1-run"
    assert body["model"] == "mock:sentinel-flash"
    assert body["dataset_id"] == dataset_id
    assert 0.0 <= body["faithfulness"] <= 1.0
    assert 0.0 <= body["pass_rate"] <= 1.0
    assert body["cost_per_request"] > 0
    assert body["p95_latency_ms"] > 0
    assert body["git_commit"]  # "unknown" is fine, just must be present

    # The traces this actually produced should be queryable and evaluated.
    traces = await client.get(
        "/api/v1/traces",
        params={"application_id": "experiment-runner", "model": "mock:sentinel-flash"},
    )
    assert traces.json()["total"] >= 3
    assert all(t["evaluation"] is not None for t in traces.json()["items"] if t["status"] == "ok")


@pytest.mark.asyncio
async def test_run_experiment_respects_sample_size(
    client: AsyncClient, seeded_models: AsyncSession
) -> None:
    dataset_id, prompt_id = await _seed_dataset_and_prompt(client)

    resp = await client.post(
        "/api/v1/experiments/run",
        json={
            "name": "sampled-run",
            "model": "mock:sentinel-nano",
            "prompt_id": prompt_id,
            "prompt_version": 1,
            "dataset_id": dataset_id,
            "sample_size": 1,
        },
    )
    assert resp.status_code == 201
    assert resp.json()["parameters"]["sample_size"] == 1


@pytest.mark.asyncio
async def test_run_experiment_unknown_prompt_returns_400(
    client: AsyncClient, seeded_models: AsyncSession
) -> None:
    dataset_id, _ = await _seed_dataset_and_prompt(client)

    resp = await client.post(
        "/api/v1/experiments/run",
        json={
            "name": "bad",
            "model": "mock:sentinel-flash",
            "prompt_id": "does-not-exist",
            "prompt_version": 1,
            "dataset_id": dataset_id,
        },
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_run_experiment_unknown_dataset_returns_400(
    client: AsyncClient, seeded_models: AsyncSession
) -> None:
    _, prompt_id = await _seed_dataset_and_prompt(client)

    resp = await client.post(
        "/api/v1/experiments/run",
        json={
            "name": "bad",
            "model": "mock:sentinel-flash",
            "prompt_id": prompt_id,
            "prompt_version": 1,
            "dataset_id": "does-not-exist",
        },
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_compare_two_experiments(client: AsyncClient, seeded_models: AsyncSession) -> None:
    dataset_id, prompt_id = await _seed_dataset_and_prompt(client)

    run_a = await client.post(
        "/api/v1/experiments/run",
        json={
            "name": "run-a",
            "model": "mock:sentinel-pro",
            "prompt_id": prompt_id,
            "prompt_version": 1,
            "dataset_id": dataset_id,
        },
    )
    run_b = await client.post(
        "/api/v1/experiments/run",
        json={
            "name": "run-b",
            "model": "mock:sentinel-nano",
            "prompt_id": prompt_id,
            "prompt_version": 1,
            "dataset_id": dataset_id,
        },
    )

    resp = await client.get(
        "/api/v1/experiments/compare", params={"a": run_a.json()["id"], "b": run_b.json()["id"]}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["experiment_a"]["id"] == run_a.json()["id"]
    assert body["experiment_b"]["id"] == run_b.json()["id"]
    metric_names = {m["metric_name"] for m in body["metrics"]}
    assert metric_names == {
        "faithfulness",
        "relevance",
        "hallucination_rate",
        "p95_latency_ms",
        "cost_per_request",
        "pass_rate",
    }
    for metric in body["metrics"]:
        assert metric["better"] in {"a", "b", "tie"}


@pytest.mark.asyncio
async def test_compare_unknown_experiment_returns_404(client: AsyncClient) -> None:
    resp = await client.get(
        "/api/v1/experiments/compare", params={"a": "missing-a", "b": "missing-b"}
    )
    assert resp.status_code == 404
