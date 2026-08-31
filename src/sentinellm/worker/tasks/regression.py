"""Regression detection: compares a recent window of evaluated traces per
application against the window immediately before it. A statistically
meaningful drop in faithfulness or overall quality creates a `Regression`
row with a best-effort "likely cause" derived by diffing the dominant
model/prompt version between the two windows.
"""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sentinellm.core.config import get_settings
from sentinellm.core.logging import get_logger
from sentinellm.db.models import Evaluation, EvaluationMetric, Regression, Trace

logger = get_logger(__name__)

_WINDOW_SIZE = 30
_DEDUPE_WINDOW = timedelta(hours=1)


def _severity_for(delta_pct: float) -> str:
    magnitude = abs(delta_pct)
    if magnitude >= 35:
        return "critical"
    if magnitude >= 20:
        return "high"
    if magnitude >= 10:
        return "medium"
    return "low"


async def _windowed_traces(
    session: AsyncSession, application_id: str, offset: int, limit: int
) -> list[Trace]:
    stmt = (
        select(Trace)
        .where(Trace.application_id == application_id, Trace.evaluation_status == "completed")
        .order_by(Trace.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    return list((await session.execute(stmt)).scalars().all())


def _dominant(values: list[str]) -> str:
    if not values:
        return "unknown"
    return Counter(values).most_common(1)[0][0]


async def detect_regressions_for_application(
    session: AsyncSession, application_id: str
) -> list[Regression]:
    settings = get_settings()
    current = await _windowed_traces(session, application_id, offset=0, limit=_WINDOW_SIZE)
    previous = await _windowed_traces(
        session, application_id, offset=_WINDOW_SIZE, limit=_WINDOW_SIZE
    )

    if len(current) < 10 or len(previous) < 10:
        return []

    current_ids = [t.id for t in current]
    previous_ids = [t.id for t in previous]
    current_evals = (
        (await session.execute(select(Evaluation).where(Evaluation.trace_id.in_(current_ids))))
        .scalars()
        .all()
    )
    previous_evals = (
        (await session.execute(select(Evaluation).where(Evaluation.trace_id.in_(previous_ids))))
        .scalars()
        .all()
    )

    if not current_evals or not previous_evals:
        return []

    async def _avg_deterministic_metric(metric_name: str, eval_ids: list[str]) -> float | None:
        stmt = select(EvaluationMetric.score).where(
            EvaluationMetric.evaluation_id.in_(eval_ids),
            EvaluationMetric.metric_name == metric_name,
        )
        scores = (await session.execute(stmt)).scalars().all()
        return (sum(scores) / len(scores)) if scores else None

    current_eval_ids = [e.id for e in current_evals]
    previous_eval_ids = [e.id for e in previous_evals]

    windows: dict[str, tuple[float, float]] = {
        "overall_quality": (
            sum(e.overall_quality for e in current_evals) / len(current_evals),
            sum(e.overall_quality for e in previous_evals) / len(previous_evals),
        ),
        "hallucination_score": (
            sum(e.hallucination_score for e in current_evals) / len(current_evals),
            sum(e.hallucination_score for e in previous_evals) / len(previous_evals),
        ),
    }
    for deterministic_metric in ("faithfulness", "relevance"):
        current_metric_avg = await _avg_deterministic_metric(deterministic_metric, current_eval_ids)
        previous_metric_avg = await _avg_deterministic_metric(
            deterministic_metric, previous_eval_ids
        )
        if current_metric_avg is not None and previous_metric_avg is not None:
            windows[deterministic_metric] = (current_metric_avg, previous_metric_avg)

    created: list[Regression] = []
    for metric_name, (current_avg, previous_avg) in windows.items():
        if previous_avg == 0:
            continue

        if metric_name == "hallucination_score":
            delta_pct = ((current_avg - previous_avg) / previous_avg) * 100  # increase is bad
        else:
            delta_pct = ((previous_avg - current_avg) / previous_avg) * 100  # decrease is bad

        if delta_pct < settings.regression_threshold_pct:
            continue

        recently_flagged = await session.execute(
            select(Regression).where(
                Regression.application_id == application_id,
                Regression.metric_name == metric_name,
                Regression.detected_at >= datetime.now(UTC) - _DEDUPE_WINDOW,
            )
        )
        if recently_flagged.scalar_one_or_none() is not None:
            continue

        current_models = _dominant([t.model for t in current])
        previous_models = _dominant([t.model for t in previous])
        current_prompt = _dominant(
            [f"{t.prompt_id}:v{t.prompt_version}" for t in current if t.prompt_id]
        )
        previous_prompt = _dominant(
            [f"{t.prompt_id}:v{t.prompt_version}" for t in previous if t.prompt_id]
        )

        causes = []
        if current_models != previous_models:
            causes.append(f"model changed {previous_models} -> {current_models}")
        if current_prompt != previous_prompt and current_prompt != "unknown":
            causes.append(f"prompt changed {previous_prompt} -> {current_prompt}")
        likely_cause = (
            "; ".join(causes)
            if causes
            else "no model/prompt change detected in this window — investigate retrieval or upstream data drift"
        )

        regression = Regression(
            metric_name=metric_name,
            previous_value=round(previous_avg, 4),
            new_value=round(current_avg, 4),
            delta_pct=round(delta_pct, 2),
            severity=_severity_for(delta_pct),
            application_id=application_id,
            likely_cause=likely_cause,
        )
        session.add(regression)
        created.append(regression)
        logger.warning(
            "regression_detected",
            application_id=application_id,
            metric_name=metric_name,
            delta_pct=regression.delta_pct,
            severity=regression.severity,
        )

    if created:
        await session.commit()
    return created


async def detect_regressions(session: AsyncSession) -> list[Regression]:
    application_ids = (
        (await session.execute(select(Trace.application_id).distinct())).scalars().all()
    )
    results: list[Regression] = []
    for application_id in application_ids:
        results.extend(await detect_regressions_for_application(session, application_id))
    return results
