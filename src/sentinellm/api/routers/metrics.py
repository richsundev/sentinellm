"""Aggregate metrics endpoints backing the overview and cost dashboards.

Percentiles and cost insights are computed directly from stored traces/
evaluations in the requested window (Python-side, over a bounded sample) —
nothing here is a canned or hand-authored number.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sentinellm.api.deps import RequireRead, get_db
from sentinellm.api.schemas.metrics import (
    ApplicationCost,
    CostSummaryOut,
    DailyCost,
    ModelCost,
    ModelUsage,
    OverviewMetricsOut,
    ProviderReliability,
    TimeseriesPoint,
)
from sentinellm.db.models import Evaluation, EvaluationMetric, Trace, TraceFeedback

router = APIRouter(prefix="/api/v1/metrics", tags=["metrics"])

_RANGE_TO_DELTA = {
    "1h": timedelta(hours=1),
    "24h": timedelta(hours=24),
    "7d": timedelta(days=7),
    "30d": timedelta(days=30),
}
_SAMPLE_CAP = 5000
_BUCKET_COUNT = 24
_HUMAN_AGREEMENT_QUALITY_THRESHOLD = 0.7


def _percentile(sorted_values: list[float], p: float) -> float:
    if not sorted_values:
        return 0.0
    idx = min(len(sorted_values) - 1, int(p * len(sorted_values)))
    return round(sorted_values[idx], 2)


@router.get("/overview", response_model=OverviewMetricsOut, dependencies=[Depends(RequireRead)])
async def overview(
    db: AsyncSession = Depends(get_db),
    time_range: str = Query(default="24h", alias="range", pattern="^(1h|24h|7d|30d)$"),
    model: str | None = None,
    provider: str | None = None,
    application_id: str | None = None,
    environment: str | None = None,
) -> OverviewMetricsOut:
    since = datetime.now(UTC) - _RANGE_TO_DELTA[time_range]
    stmt = select(Trace).where(Trace.created_at >= since)
    for column, value in (
        (Trace.model, model),
        (Trace.provider, provider),
        (Trace.application_id, application_id),
        (Trace.environment, environment),
    ):
        if value:
            stmt = stmt.where(column == value)
    stmt = stmt.order_by(Trace.created_at.asc()).limit(_SAMPLE_CAP)
    traces = (await db.execute(stmt)).scalars().all()

    if not traces:
        return OverviewMetricsOut(
            request_volume=0,
            error_rate=0.0,
            p50_latency_ms=0.0,
            p95_latency_ms=0.0,
            p99_latency_ms=0.0,
            avg_cost_per_request=0.0,
            avg_tokens_per_request=0.0,
            hallucination_rate=0.0,
            avg_faithfulness=0.0,
            avg_relevance=0.0,
            model_usage=[],
            provider_reliability=[],
            timeseries=[],
            human_feedback_count=0,
            human_judge_agreement_rate=None,
            cache_hit_count=0,
            cache_hit_rate=0.0,
            estimated_cache_savings=0.0,
        )

    latencies = sorted(t.latency_ms for t in traces)
    error_count = sum(1 for t in traces if t.status == "error")
    avg_cost = sum(t.estimated_cost for t in traces) / len(traces)
    avg_tokens = sum(t.input_tokens + t.output_tokens for t in traces) / len(traces)

    trace_ids = [t.id for t in traces]
    evaluations = (
        (await db.execute(select(Evaluation).where(Evaluation.trace_id.in_(trace_ids))))
        .scalars()
        .all()
    )
    metric_rows = (
        await db.execute(
            select(EvaluationMetric.metric_name, EvaluationMetric.score)
            .join(Evaluation, Evaluation.id == EvaluationMetric.evaluation_id)
            .where(Evaluation.trace_id.in_(trace_ids))
        )
    ).all()
    faithfulness = [r.score for r in metric_rows if r.metric_name == "faithfulness"]
    relevance = [r.score for r in metric_rows if r.metric_name == "relevance"]
    hallucination_scores = [e.hallucination_score for e in evaluations]

    feedback_rows = (
        (await db.execute(select(TraceFeedback).where(TraceFeedback.trace_id.in_(trace_ids))))
        .scalars()
        .all()
    )
    quality_by_trace_id = {e.trace_id: e.overall_quality for e in evaluations}
    agreements = 0
    compared = 0
    for feedback in feedback_rows:
        quality = quality_by_trace_id.get(feedback.trace_id)
        if quality is None:
            continue
        compared += 1
        judged_good = quality >= _HUMAN_AGREEMENT_QUALITY_THRESHOLD
        human_liked = feedback.rating == "up"
        if judged_good == human_liked:
            agreements += 1
    human_judge_agreement_rate = round(agreements / compared, 4) if compared else None

    cache_hit_count = sum(1 for t in traces if t.cache_hit)
    miss_costs = [t.estimated_cost for t in traces if not t.cache_hit and t.status == "ok"]
    avg_miss_cost = sum(miss_costs) / len(miss_costs) if miss_costs else 0.0
    estimated_cache_savings = round(cache_hit_count * avg_miss_cost, 6)

    usage: dict[str, int] = {}
    provider_totals: dict[str, list[int]] = {}
    for t in traces:
        usage[t.model] = usage.get(t.model, 0) + 1
        bucket = provider_totals.setdefault(t.provider, [0, 0])
        bucket[1] += 1
        if t.status == "ok":
            bucket[0] += 1

    bucket_span = (datetime.now(UTC) - since) / _BUCKET_COUNT
    buckets: list[dict] = [
        {"volume": 0, "latencies": [], "cost": 0.0} for _ in range(_BUCKET_COUNT)
    ]
    for t in traces:
        elapsed = (
            t.created_at.replace(tzinfo=UTC) - since
            if t.created_at.tzinfo is None
            else t.created_at - since
        )
        idx = min(_BUCKET_COUNT - 1, max(0, int(elapsed / bucket_span)))
        buckets[idx]["volume"] += 1
        buckets[idx]["latencies"].append(t.latency_ms)
        buckets[idx]["cost"] += t.estimated_cost

    timeseries = [
        TimeseriesPoint(
            timestamp=(since + bucket_span * (i + 1)).isoformat(),
            volume=b["volume"],
            p95_latency_ms=_percentile(sorted(b["latencies"]), 0.95),
            cost=round(b["cost"], 6),
        )
        for i, b in enumerate(buckets)
    ]

    return OverviewMetricsOut(
        request_volume=len(traces),
        error_rate=round(error_count / len(traces), 4),
        p50_latency_ms=_percentile(latencies, 0.50),
        p95_latency_ms=_percentile(latencies, 0.95),
        p99_latency_ms=_percentile(latencies, 0.99),
        avg_cost_per_request=round(avg_cost, 6),
        avg_tokens_per_request=round(avg_tokens, 1),
        hallucination_rate=round(sum(hallucination_scores) / len(hallucination_scores), 4)
        if hallucination_scores
        else 0.0,
        avg_faithfulness=round(sum(faithfulness) / len(faithfulness), 4) if faithfulness else 0.0,
        avg_relevance=round(sum(relevance) / len(relevance), 4) if relevance else 0.0,
        model_usage=[
            ModelUsage(model=m, count=c) for m, c in sorted(usage.items(), key=lambda kv: -kv[1])
        ],
        provider_reliability=[
            ProviderReliability(provider=p, success_rate=round(ok / total, 4) if total else 0.0)
            for p, (ok, total) in provider_totals.items()
        ],
        timeseries=timeseries,
        human_feedback_count=len(feedback_rows),
        human_judge_agreement_rate=human_judge_agreement_rate,
        cache_hit_count=cache_hit_count,
        cache_hit_rate=round(cache_hit_count / len(traces), 4),
        estimated_cache_savings=estimated_cache_savings,
    )


def _compute_cost_insight(per_model: dict[str, dict[str, float]]) -> str | None:
    """Finds a genuine "cheaper model, similar quality" pair from observed
    per-model averages in the window, or returns None if no such pair exists.
    """
    candidates = [(m, s) for m, s in per_model.items() if s["count"] >= 3]
    if len(candidates) < 2:
        return None
    best_quality = max(candidates, key=lambda kv: kv[1]["quality"])
    for model, stats in sorted(candidates, key=lambda kv: kv[1]["cost"]):
        if model == best_quality[0]:
            continue
        quality_gap = best_quality[1]["quality"] - stats["quality"]
        if stats["cost"] < best_quality[1]["cost"] and quality_gap <= 0.07:
            pct_cheaper = (
                (1 - stats["cost"] / best_quality[1]["cost"]) * 100
                if best_quality[1]["cost"] > 0
                else 0
            )
            return (
                f"{model} costs {pct_cheaper:.0f}% less per request than {best_quality[0]} "
                f"while producing quality within {quality_gap:.2f} "
                f"({stats['quality']:.2f} vs {best_quality[1]['quality']:.2f}, observed over "
                f"{int(stats['count'])} and {int(best_quality[1]['count'])} requests respectively)."
            )
    return None


@router.get("/cost", response_model=CostSummaryOut, dependencies=[Depends(RequireRead)])
async def cost_summary(
    db: AsyncSession = Depends(get_db),
    time_range: str = Query(default="30d", alias="range", pattern="^(1h|24h|7d|30d)$"),
) -> CostSummaryOut:
    since = datetime.now(UTC) - _RANGE_TO_DELTA[time_range]
    traces = (
        (await db.execute(select(Trace).where(Trace.created_at >= since).limit(_SAMPLE_CAP)))
        .scalars()
        .all()
    )

    if not traces:
        return CostSummaryOut(
            total_cost=0.0, daily=[], by_model=[], by_application=[], insight_text=None
        )

    total_cost = sum(t.estimated_cost for t in traces)
    daily: dict[str, float] = {}
    by_model: dict[str, float] = {}
    by_application: dict[str, float] = {}
    per_model_quality: dict[str, dict[str, float]] = {}

    trace_ids = [t.id for t in traces]
    evaluations = {
        e.trace_id: e
        for e in (await db.execute(select(Evaluation).where(Evaluation.trace_id.in_(trace_ids))))
        .scalars()
        .all()
    }

    for t in traces:
        day = t.created_at.date().isoformat()
        daily[day] = daily.get(day, 0.0) + t.estimated_cost
        by_model[t.model] = by_model.get(t.model, 0.0) + t.estimated_cost
        by_application[t.application_id] = (
            by_application.get(t.application_id, 0.0) + t.estimated_cost
        )

        stats = per_model_quality.setdefault(t.model, {"cost": 0.0, "quality": 0.0, "count": 0.0})
        stats["cost"] += t.estimated_cost
        stats["count"] += 1
        evaluation = evaluations.get(t.id)
        if evaluation is not None:
            stats["quality"] += evaluation.overall_quality

    for stats in per_model_quality.values():
        if stats["count"] > 0:
            stats["cost"] = stats["cost"] / stats["count"]
            stats["quality"] = stats["quality"] / stats["count"]

    return CostSummaryOut(
        total_cost=round(total_cost, 6),
        daily=[DailyCost(date=d, cost=round(c, 6)) for d, c in sorted(daily.items())],
        by_model=[
            ModelCost(model=m, cost=round(c, 6))
            for m, c in sorted(by_model.items(), key=lambda kv: -kv[1])
        ],
        by_application=[
            ApplicationCost(application_id=a, cost=round(c, 6))
            for a, c in sorted(by_application.items(), key=lambda kv: -kv[1])
        ],
        insight_text=_compute_cost_insight(per_model_quality),
    )
