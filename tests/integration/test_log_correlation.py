"""`trace_id_var` fed the JSON log formatter but nothing ever set it, so log
lines from a generation or an evaluation carried no trace id to search for."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from sentinellm.api.schemas.generate import GenerateRequest
from sentinellm.core.ids import new_trace_id
from sentinellm.core.logging import trace_id_var
from sentinellm.db.models import Trace
from sentinellm.embeddings.mock_provider import MockEmbeddingProvider
from sentinellm.evaluation.pipeline import EvaluationPipeline
from sentinellm.services.generation import generate
from sentinellm.worker.tasks.evaluate import process_evaluation_job


@pytest.mark.asyncio
async def test_generation_logs_carry_the_traces_id(seeded_models: AsyncSession) -> None:
    seen: list[str | None] = []
    trace_id_var.set(None)

    trace = await generate(
        seeded_models,
        GenerateRequest(
            application_id="corr",
            question="hello",
            preferred_model="mock:sentinel-flash",
            use_cache=False,
            evaluate=False,
        ),
    )
    seen.append(trace_id_var.get())

    assert seen == [trace.trace_id]


@pytest.mark.asyncio
async def test_evaluation_logs_carry_the_traces_id_and_it_is_cleared_afterwards(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    trace = Trace(
        trace_id=new_trace_id(),
        request_id="r",
        application_id="corr",
        model="mock:sentinel-flash",
        provider="mock",
        prompt="q",
        response="a",
    )
    db_session.add(trace)
    await db_session.commit()

    pipeline = EvaluationPipeline(MockEmbeddingProvider(), judge_provider=None, run_judge=False)
    during: list[str | None] = []
    original = pipeline.run_and_persist

    async def spy(session: AsyncSession, t: Trace):
        during.append(trace_id_var.get())
        return await original(session, t)

    monkeypatch.setattr(pipeline, "run_and_persist", spy)
    trace_id_var.set(None)

    await process_evaluation_job(db_session, pipeline, trace.id)

    assert during == [trace.trace_id]
    # One consumer processes many jobs in a row: no id may leak into the next.
    assert trace_id_var.get() is None
