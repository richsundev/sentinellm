import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sentinellm.db.models import Trace
from sentinellm.embeddings.mock_provider import MockEmbeddingProvider
from sentinellm.evaluation.pipeline import EvaluationPipeline


@pytest.mark.asyncio
async def test_overview_reports_zero_feedback_when_none_given(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/metrics/overview", params={"range": "24h"})
    body = resp.json()
    assert body["human_feedback_count"] == 0
    assert body["human_judge_agreement_rate"] is None


@pytest.mark.asyncio
async def test_overview_computes_human_judge_agreement(
    client: AsyncClient, seeded_models: AsyncSession
) -> None:
    resp = await client.post(
        "/api/v1/generate",
        json={
            "application_id": "feedback-app",
            "question": "What is your refund policy?",
            "system_prompt": "Refunds are honored within 30 days of purchase.",
            "preferred_model": "mock:sentinel-pro",
            "use_cache": False,
            "evaluate": False,
        },
    )
    trace_id = resp.json()["trace_id"]

    # No worker runs in the test suite (evaluation is normally async), so
    # evaluate inline here — same pattern scripts/seed_demo.py and
    # services/experiments.py use.
    pipeline = EvaluationPipeline(MockEmbeddingProvider(), judge_provider=None, run_judge=False)
    trace = (
        await seeded_models.execute(select(Trace).where(Trace.trace_id == trace_id))
    ).scalar_one()
    await pipeline.run_and_persist(seeded_models, trace)
    await seeded_models.commit()

    await client.post(f"/api/v1/traces/{trace_id}/feedback", json={"rating": "up"})

    overview = await client.get("/api/v1/metrics/overview", params={"range": "24h"})
    body = overview.json()
    assert body["human_feedback_count"] == 1
    assert body["human_judge_agreement_rate"] in {
        0.0,
        1.0,
    }  # single-sample: either agrees or doesn't
