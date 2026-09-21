"""Experiments feed the prompt-promotion gate, so their aggregates must be
honest: failed requests count against `pass_rate`, the same dataset sample is
used on every run, and record text is never interpreted as template syntax."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from sentinellm.api.schemas.experiment import ExperimentRunRequest
from sentinellm.core.ids import new_trace_id
from sentinellm.db.models import Dataset, DatasetRecord, Evaluation, PromptVersion, Trace
from sentinellm.services import experiments
from sentinellm.services.experiments import _aggregate_into_experiment, render_prompt_template


def _request(**over) -> ExperimentRunRequest:
    fields = {
        "name": "exp",
        "model": "mock:sentinel-flash",
        "prompt_id": "p",
        "prompt_version": 1,
        "dataset_id": "d",
    }
    fields.update(over)
    return ExperimentRunRequest(**fields)


async def _trace(session: AsyncSession, *, status: str, quality: float | None) -> Trace:
    trace = Trace(
        trace_id=new_trace_id(),
        request_id="r",
        application_id="a",
        model="mock:m",
        provider="mock",
        prompt="q",
        response="a" if status == "ok" else "",
        status=status,
        latency_ms=100.0,
        estimated_cost=0.001,
        evaluation_status="skipped",
    )
    session.add(trace)
    await session.flush()
    if quality is not None:
        session.add(Evaluation(trace_id=trace.id, overall_quality=quality, hallucination_score=0.0))
    await session.flush()
    return trace


# --- pass_rate ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_failed_requests_count_against_the_pass_rate(db_session: AsyncSession) -> None:
    """2 of 4 requests failed outright. pass_rate used to be computed over only
    the *evaluated* (successful) ones, reporting 100% — enough to clear the
    promotion gate for a prompt that fails half the time."""
    traces = [
        await _trace(db_session, status="ok", quality=0.9),
        await _trace(db_session, status="ok", quality=0.9),
        await _trace(db_session, status="error", quality=None),
        await _trace(db_session, status="error", quality=None),
    ]

    experiment = await _aggregate_into_experiment(db_session, _request(), traces)

    assert experiment.pass_rate == pytest.approx(0.5)


@pytest.mark.asyncio
async def test_pass_rate_still_reflects_quality_of_the_successful_requests(
    db_session: AsyncSession,
) -> None:
    traces = [
        await _trace(db_session, status="ok", quality=0.9),
        await _trace(db_session, status="ok", quality=0.2),
    ]
    experiment = await _aggregate_into_experiment(
        db_session, _request(quality_pass_threshold=0.7), traces
    )
    assert experiment.pass_rate == pytest.approx(0.5)


@pytest.mark.asyncio
async def test_an_experiment_where_everything_failed_has_a_zero_pass_rate(
    db_session: AsyncSession,
) -> None:
    traces = [await _trace(db_session, status="error", quality=None) for _ in range(3)]
    experiment = await _aggregate_into_experiment(db_session, _request(), traces)
    assert experiment.pass_rate == 0.0


# --- sampling ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sample_size_selects_a_stable_subset_of_the_dataset(
    db_session: AsyncSession,
) -> None:
    """`LIMIT n` with no ORDER BY leaves the choice to the database, so two
    runs asked for 'the first 3 records' could compare different records —
    invalidating any A/B comparison. Insertion order here is the reverse of
    id order, so an unordered query returns the wrong three."""
    db_session.add(Dataset(id="ds", name="d", version="v1"))
    db_session.add(
        PromptVersion(prompt_id="p", version=1, template="{{question}}", variables=[], author="t")
    )
    for i in reversed(range(8)):
        db_session.add(
            DatasetRecord(id=f"rec-{i}", dataset_id="ds", question=f"question {i}", context="c")
        )
    await db_session.commit()

    experiment = await experiments.run_experiment(
        db_session, _request(dataset_id="ds", sample_size=3, application_id="stable-app")
    )

    from sqlalchemy import select

    prompts = (
        (await db_session.execute(select(Trace.prompt).where(Trace.application_id == "stable-app")))
        .scalars()
        .all()
    )
    assert sorted(prompts) == ["question 0", "question 1", "question 2"]
    assert experiment.parameters["sample_size"] == 3


# --- template rendering -------------------------------------------------------------


def test_record_text_that_looks_like_a_placeholder_is_not_expanded() -> None:
    """Substituting `context` first and `question` second meant a context
    containing the literal `{{question}}` had it replaced with the question."""
    rendered = render_prompt_template(
        "C: {{context}} | Q: {{question}}",
        context="docs mention {{question}} syntax",
        question="what is x?",
    )
    assert rendered == "C: docs mention {{question}} syntax | Q: what is x?"


def test_a_repeated_and_an_absent_placeholder_render_correctly() -> None:
    assert (
        render_prompt_template("{{question}} / {{question}} / {{other}}", context="", question="Q")
        == "Q / Q / {{other}}"
    )
