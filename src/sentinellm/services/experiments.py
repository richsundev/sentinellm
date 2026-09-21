"""Runs a real evaluation experiment: a (model, prompt version) pair against
every record in a dataset, using the platform's own `/generate` pipeline and
evaluation pipeline, then aggregates the results into an `Experiment` row.

This is what turns the dataset/prompt/evaluation subsystems — which
otherwise only ever produce numbers via `scripts/seed_demo.py` — into an
on-demand capability: "run this prompt+model against this dataset and tell
me how it did," which is the platform's headline "Evaluation Run" workflow.

Design note: this runs synchronously within the request, deliberately
mirroring the seed script's precedent (see docs/design-decisions.md #3)
rather than adding a second async job type to the worker. An experiment run
is an explicitly-triggered, infrequent batch operation — not a hot-path
write — and `sample_size` is capped (see `ExperimentRunRequest`) to keep
worst-case latency bounded. A true "fire-and-poll" async job would be the
natural upgrade if experiment datasets grow into the hundreds of records.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from sentinellm.api.schemas.experiment import ExperimentRunRequest, MetricComparison
from sentinellm.api.schemas.generate import GenerateRequest
from sentinellm.api.schemas.trace import RetrievedDocumentIn
from sentinellm.core.git import get_git_commit
from sentinellm.core.logging import get_logger
from sentinellm.db.models import (
    Dataset,
    DatasetRecord,
    Evaluation,
    Experiment,
    PromptVersion,
    Trace,
)
from sentinellm.services.evaluation_factory import get_evaluation_pipeline
from sentinellm.services.generation import generate
from sentinellm.services.prompts import render_template

logger = get_logger(__name__)


class ExperimentInputError(ValueError):
    """Raised for a caller-fixable problem (unknown prompt/dataset, empty
    dataset) — routers translate this to a 404/400, not a 500."""


def render_prompt_template(template: str, *, context: str, question: str) -> str:
    """`{{context}}` / `{{question}}` substitution (other placeholders are left
    as written — see `services.prompts.render_template`)."""
    return render_template(template, {"context": context, "question": question}, strict=False)


async def run_experiment(session: AsyncSession, request: ExperimentRunRequest) -> Experiment:
    prompt_version = (
        await session.execute(
            select(PromptVersion).where(
                PromptVersion.prompt_id == request.prompt_id,
                PromptVersion.version == request.prompt_version,
            )
        )
    ).scalar_one_or_none()
    if prompt_version is None:
        raise ExperimentInputError(
            f"prompt '{request.prompt_id}' v{request.prompt_version} not found"
        )

    dataset = await session.get(Dataset, request.dataset_id)
    if dataset is None:
        raise ExperimentInputError(f"dataset '{request.dataset_id}' not found")

    # Ordered, so `sample_size` picks the same records on every run — an A/B
    # comparison of two runs is meaningless if they saw different samples.
    records_stmt = (
        select(DatasetRecord)
        .where(DatasetRecord.dataset_id == request.dataset_id)
        .order_by(DatasetRecord.id)
    )
    if request.sample_size:
        records_stmt = records_stmt.limit(request.sample_size)
    records = (await session.execute(records_stmt)).scalars().all()
    if not records:
        raise ExperimentInputError(f"dataset '{request.dataset_id}' has no records")

    pipeline = get_evaluation_pipeline()
    traces: list[Trace] = []
    for record in records:
        retrieved = (
            [RetrievedDocumentIn(doc_id=record.id, content=record.context, score=1.0, rank=0)]
            if record.context
            else []
        )
        gen_request = GenerateRequest(
            application_id=request.application_id,
            question=record.question,
            retrieved_documents=retrieved,
            preferred_model=request.model,
            use_cache=False,
            # Served like production traffic: `/generate` renders the template
            # with the record's question and context (once — passing it as a
            # system prompt *and* attaching the context duplicated it).
            prompt_id=request.prompt_id,
            prompt_version=request.prompt_version,
            prompt_variables={},
            evaluate=False,  # evaluated inline below, not via the async queue
            metadata={"experiment": request.name},
        )
        trace = await generate(session, gen_request)
        traces.append(trace)

    for trace in traces:
        if trace.status == "ok":
            await pipeline.run_and_persist(session, trace)
            trace.evaluation_status = "completed"
    await session.flush()

    experiment = await _aggregate_into_experiment(session, request, traces)
    await session.commit()
    logger.info(
        "experiment_run_completed",
        name=request.name,
        model=request.model,
        traces=len(traces),
        overall_quality=experiment.pass_rate,
    )
    return experiment


async def _aggregate_into_experiment(
    session: AsyncSession, request: ExperimentRunRequest, traces: list[Trace]
) -> Experiment:
    trace_ids = [t.id for t in traces]
    evaluations = (
        (
            await session.execute(
                select(Evaluation)
                .where(Evaluation.trace_id.in_(trace_ids))
                .options(selectinload(Evaluation.metrics))
            )
        )
        .scalars()
        .all()
    )

    faithfulness_scores: list[float] = []
    relevance_scores: list[float] = []
    for evaluation in evaluations:
        for metric in evaluation.metrics:
            if metric.metric_name == "faithfulness":
                faithfulness_scores.append(metric.score)
            elif metric.metric_name == "relevance":
                relevance_scores.append(metric.score)

    hallucination_scores = [e.hallucination_score for e in evaluations]
    pass_count = sum(1 for e in evaluations if e.overall_quality >= request.quality_pass_threshold)

    ok_traces = [t for t in traces if t.status == "ok"]
    latencies = sorted(t.latency_ms for t in ok_traces) or [0.0]
    costs = [t.estimated_cost for t in ok_traces] or [0.0]
    p95_latency = latencies[min(len(latencies) - 1, int(0.95 * len(latencies)))]

    experiment = Experiment(
        name=request.name,
        model=request.model,
        prompt_id=request.prompt_id,
        prompt_version=request.prompt_version,
        dataset_id=request.dataset_id,
        faithfulness=round(sum(faithfulness_scores) / len(faithfulness_scores), 4)
        if faithfulness_scores
        else 0.0,
        relevance=round(sum(relevance_scores) / len(relevance_scores), 4)
        if relevance_scores
        else 0.0,
        hallucination_rate=round(sum(hallucination_scores) / len(hallucination_scores), 4)
        if hallucination_scores
        else 0.0,
        p95_latency_ms=round(p95_latency, 2),
        cost_per_request=round(sum(costs) / len(costs), 6),
        # Over *all* requests: one that failed outright didn't pass. (Dividing
        # by the evaluated ones let a prompt that fails half its requests
        # report 100%, and this number gates prompt promotion.)
        pass_rate=round(pass_count / len(traces), 4) if traces else 0.0,
        git_commit=get_git_commit(),
        parameters={**request.parameters, "sample_size": len(traces)},
    )
    session.add(experiment)
    await session.flush()
    return experiment


_COMPARISON_METRICS: list[tuple[str, str]] = [
    ("faithfulness", "higher"),
    ("relevance", "higher"),
    ("hallucination_rate", "lower"),
    ("p95_latency_ms", "lower"),
    ("cost_per_request", "lower"),
    ("pass_rate", "higher"),
]


def compare_experiments(
    experiment_a: Experiment, experiment_b: Experiment
) -> list[MetricComparison]:
    comparisons = []
    for metric_name, better_direction in _COMPARISON_METRICS:
        value_a = getattr(experiment_a, metric_name)
        value_b = getattr(experiment_b, metric_name)
        delta = round(value_b - value_a, 6)
        delta_pct = round((delta / value_a) * 100, 2) if value_a else None

        if value_a == value_b:
            better = "tie"
        elif better_direction == "higher":
            better = "b" if value_b > value_a else "a"
        else:
            better = "b" if value_b < value_a else "a"

        comparisons.append(
            MetricComparison(
                metric_name=metric_name,
                value_a=value_a,
                value_b=value_b,
                delta=delta,
                delta_pct=delta_pct,
                better=better,
            )
        )
    return comparisons
