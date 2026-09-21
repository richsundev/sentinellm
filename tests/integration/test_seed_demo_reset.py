"""`scripts/seed_demo.py --force` ("reseed even if demo data already exists")
crashed on the first unique constraint it hit (the model catalog). Forcing a
reseed now clears the demo's own data first — and nothing else."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from sentinellm.core.ids import new_trace_id
from sentinellm.db.models import (
    APIKey,
    Application,
    Dataset,
    DatasetRecord,
    Evaluation,
    EvaluationMetric,
    ModelPricing,
    ModelRollout,
    PromptRollout,
    PromptVersion,
    Trace,
    TraceSpan,
)

_SPEC = importlib.util.spec_from_file_location(
    "seed_demo_script", Path(__file__).resolve().parents[2] / "scripts" / "seed_demo.py"
)
assert _SPEC and _SPEC.loader
seed_demo = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(seed_demo)


async def _count(session: AsyncSession, model: type) -> int:
    return (await session.execute(select(func.count()).select_from(model))).scalar_one()


async def _trace(session: AsyncSession, application_id: str) -> Trace:
    trace = Trace(
        trace_id=new_trace_id(),
        request_id="r",
        application_id=application_id,
        model="mock:sentinel-flash",
        provider="mock",
        prompt="q",
        response="a",
    )
    trace.spans = [TraceSpan(name="s", start_ms=0, duration_ms=1)]
    session.add(trace)
    await session.flush()
    evaluation = Evaluation(trace_id=trace.id, overall_quality=0.5, hallucination_score=0.1)
    evaluation.metrics = [EvaluationMetric(metric_name="m", score=1.0, reason="r")]
    session.add(evaluation)
    return trace


@pytest.mark.asyncio
async def test_seeding_the_model_catalog_twice_does_not_collide(db_session: AsyncSession) -> None:
    await seed_demo._seed_models(db_session)
    await db_session.commit()

    await seed_demo._seed_models(db_session)  # used to raise IntegrityError
    await db_session.commit()

    assert await _count(db_session, ModelPricing) == len(seed_demo.DEFAULT_MODEL_CATALOG)


@pytest.mark.asyncio
async def test_a_reset_removes_the_demo_data_and_only_the_demo_data(
    db_session: AsyncSession,
) -> None:
    demo = Application(name=seed_demo.APPLICATION_NAME)
    checkout = Application(name=seed_demo.CHECKOUT_APPLICATION_NAME)
    other = Application(name="customer-app")
    db_session.add_all([demo, checkout, other])
    await db_session.flush()
    db_session.add(APIKey(application_id=demo.id, name="k", key_hash="h", key_prefix="p"))
    dataset = Dataset(name="support-bench", version="v1")
    dataset.records = [DatasetRecord(question="q")]
    other_dataset = Dataset(name="customers-own", version="v1")
    db_session.add_all(
        [
            dataset,
            other_dataset,
            PromptVersion(prompt_id="support-answer", version=1, template="t"),
            PromptVersion(prompt_id="checkout-answer", version=1, template="t"),
            PromptVersion(prompt_id="customer-prompt", version=1, template="t"),
            ModelRollout(
                application_id=checkout.id,
                incumbent_model="a",
                challenger_model="b",
                stage="running",
            ),
            PromptRollout(
                application_id=checkout.id,
                prompt_id="checkout-answer",
                incumbent_version=1,
                challenger_version=2,
                stage="running",
            ),
        ]
    )
    await _trace(db_session, demo.id)  # traces are recorded under the row's id...
    await _trace(db_session, seed_demo.APPLICATION_NAME)  # ...or under its name
    kept = await _trace(db_session, other.id)
    await db_session.commit()

    await seed_demo._reset_demo_data(db_session)
    await db_session.commit()

    assert await _count(db_session, Trace) == 1
    assert (await db_session.execute(select(Trace.id))).scalar_one() == kept.id
    assert await _count(db_session, TraceSpan) == 1
    assert await _count(db_session, Evaluation) == 1
    assert await _count(db_session, EvaluationMetric) == 1
    assert [a.name for a in (await db_session.execute(select(Application))).scalars()] == [
        "customer-app"
    ]
    assert await _count(db_session, APIKey) == 0
    assert [d.name for d in (await db_session.execute(select(Dataset))).scalars()] == [
        "customers-own"
    ]
    assert await _count(db_session, DatasetRecord) == 0
    assert [p.prompt_id for p in (await db_session.execute(select(PromptVersion))).scalars()] == [
        "customer-prompt"
    ]
    assert await _count(db_session, ModelRollout) == 0
    assert await _count(db_session, PromptRollout) == 0


@pytest.mark.asyncio
async def test_a_reset_on_an_empty_database_is_a_no_op(db_session: AsyncSession) -> None:
    await seed_demo._reset_demo_data(db_session)
    await db_session.commit()
