"""Evaluation job handler: claims a trace, runs the evaluation pipeline,
persists the result idempotently, and marks the trace's evaluation_status.

Claim step: sets `evaluation_status = 'evaluating'` with a `WHERE
evaluation_status = 'pending'` guard before doing any work, so if the same
job is delivered twice concurrently (Redis at-least-once delivery), only one
worker proceeds — the other sees zero rows affected and skips.
"""

from __future__ import annotations

from sqlalchemy import update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from sentinellm.core.logging import get_logger
from sentinellm.db.models import Trace
from sentinellm.evaluation.pipeline import EvaluationPipeline
from sentinellm.observability.metrics import EVALUATION_SCORE
from sentinellm.observability.tracing import get_tracer

logger = get_logger(__name__)


async def process_evaluation_job(
    session: AsyncSession, pipeline: EvaluationPipeline, trace_db_id: str
) -> bool:
    with get_tracer(__name__).start_as_current_span("sentinel.evaluate") as span:
        span.set_attribute("sentinel.trace_db_id", trace_db_id)
        processed = await _process_evaluation_job(session, pipeline, trace_db_id)
        span.set_attribute("sentinel.evaluated", processed)
        return processed


async def _process_evaluation_job(
    session: AsyncSession, pipeline: EvaluationPipeline, trace_db_id: str
) -> bool:
    claim: CursorResult = await session.execute(  # type: ignore[assignment]
        update(Trace)
        .where(Trace.id == trace_db_id, Trace.evaluation_status == "pending")
        .values(evaluation_status="evaluating")
    )
    if claim.rowcount == 0:
        logger.info("evaluation_job_skipped_not_pending", trace_db_id=trace_db_id)
        return False

    trace = await session.get(Trace, trace_db_id)
    if trace is None:
        logger.warning("evaluation_job_trace_missing", trace_db_id=trace_db_id)
        return False

    try:
        evaluation = await pipeline.run_and_persist(session, trace)
        trace.evaluation_status = "completed"
        for metric in evaluation.metrics:
            EVALUATION_SCORE.labels(metric_name=metric.metric_name).observe(metric.score)
        await session.commit()
        return True
    except Exception:
        await session.rollback()
        trace.evaluation_status = "failed"
        await session.commit()
        logger.exception("evaluation_job_failed", trace_db_id=trace_db_id)
        return False
