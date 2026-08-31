import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sentinellm.db.models import Evaluation, Trace
from sentinellm.embeddings.mock_provider import MockEmbeddingProvider
from sentinellm.evaluation.pipeline import EvaluationPipeline
from sentinellm.worker.tasks.evaluate import process_evaluation_job


@pytest.mark.asyncio
async def test_process_evaluation_job_marks_trace_completed(db_session: AsyncSession) -> None:
    trace = Trace(
        trace_id="trc_w1",
        request_id="req_w1",
        application_id="app-1",
        model="mock:sentinel-flash",
        provider="mock",
        prompt="q",
        response="a",
        latency_ms=100.0,
        estimated_cost=0.0001,
    )
    db_session.add(trace)
    await db_session.commit()

    pipeline = EvaluationPipeline(MockEmbeddingProvider(), judge_provider=None, run_judge=False)
    processed = await process_evaluation_job(db_session, pipeline, trace.id)

    assert processed is True
    refreshed = await db_session.get(Trace, trace.id)
    assert refreshed.evaluation_status == "completed"


@pytest.mark.asyncio
async def test_duplicate_delivery_of_same_job_is_a_no_op(db_session: AsyncSession) -> None:
    trace = Trace(
        trace_id="trc_w2",
        request_id="req_w2",
        application_id="app-1",
        model="mock:sentinel-flash",
        provider="mock",
        prompt="q",
        response="a",
        latency_ms=100.0,
        estimated_cost=0.0001,
    )
    db_session.add(trace)
    await db_session.commit()

    pipeline = EvaluationPipeline(MockEmbeddingProvider(), judge_provider=None, run_judge=False)
    first = await process_evaluation_job(db_session, pipeline, trace.id)
    second = await process_evaluation_job(db_session, pipeline, trace.id)

    assert first is True
    assert second is False  # already completed, not re-claimed

    evaluations = (
        (await db_session.execute(select(Evaluation).where(Evaluation.trace_id == trace.id)))
        .scalars()
        .all()
    )
    assert len(evaluations) == 1
