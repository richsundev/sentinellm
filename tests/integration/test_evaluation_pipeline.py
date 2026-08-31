import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sentinellm.db.models import Evaluation, Trace
from sentinellm.embeddings.mock_provider import MockEmbeddingProvider
from sentinellm.evaluation.pipeline import EvaluationPipeline
from sentinellm.llm.mock_provider import MockProvider


@pytest.mark.asyncio
async def test_run_and_persist_creates_evaluation_with_metrics_and_claims(
    db_session: AsyncSession,
) -> None:
    trace = Trace(
        trace_id="trc_test1",
        request_id="req_test1",
        application_id="app-1",
        model="mock:sentinel-flash",
        provider="mock",
        prompt="What is the refund window?",
        response="Refunds are honored within 30 days.",
        system_prompt="Refunds are honored within 30 days of purchase.",
        latency_ms=500.0,
        estimated_cost=0.001,
    )
    db_session.add(trace)
    await db_session.flush()

    pipeline = EvaluationPipeline(MockEmbeddingProvider(), judge_provider=MockProvider())
    evaluation = await pipeline.run_and_persist(db_session, trace)
    await db_session.commit()

    assert evaluation.id is not None
    assert 0.0 <= evaluation.overall_quality <= 1.0
    assert len(evaluation.metrics) >= 6
    metric_names = {m.metric_name for m in evaluation.metrics}
    assert {
        "relevance",
        "faithfulness",
        "safety",
        "latency",
        "cost_efficiency",
        "judge_quality",
    } <= metric_names


@pytest.mark.asyncio
async def test_run_and_persist_is_idempotent(db_session: AsyncSession) -> None:
    trace = Trace(
        trace_id="trc_test2",
        request_id="req_test2",
        application_id="app-1",
        model="mock:sentinel-flash",
        provider="mock",
        prompt="q",
        response="a",
        latency_ms=100.0,
        estimated_cost=0.0001,
    )
    db_session.add(trace)
    await db_session.flush()

    pipeline = EvaluationPipeline(MockEmbeddingProvider(), judge_provider=None, run_judge=False)
    first = await pipeline.run_and_persist(db_session, trace)
    await db_session.commit()
    second = await pipeline.run_and_persist(db_session, trace)
    await db_session.commit()

    assert first.id == second.id

    count = (
        (await db_session.execute(select(Evaluation).where(Evaluation.trace_id == trace.id)))
        .scalars()
        .all()
    )
    assert len(count) == 1
