"""Recovers evaluation jobs the queue lost.

Delivery is a Redis `BRPOP`: once a worker pops a job it exists nowhere else,
so a worker killed mid-evaluation (deploy, OOM) leaves its trace stuck in
`evaluating` forever, and a job pushed while Redis was down (the enqueue is
best-effort) leaves a trace `pending` with nothing queued. Neither ever got
evaluated, and neither showed up anywhere.

Every step is safe to repeat: `process_evaluation_job` claims with a
`pending`-only guard and `run_and_persist` returns an existing evaluation, so
a needless re-queue costs one skipped job, never a duplicate result.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import exists, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from sentinellm.core.logging import get_logger
from sentinellm.core.queue import enqueue_evaluation, queue_depth
from sentinellm.db.models import Evaluation, Trace
from sentinellm.observability.metrics import EVALUATION_RECOVERED_TOTAL

logger = get_logger(__name__)

# A single evaluation takes seconds (a slow judge, tens). A trace still
# `evaluating` this long after it was *created* is stuck — the margin also
# covers a job that waited in the queue before being claimed.
STUCK_EVALUATING_AFTER = timedelta(minutes=10)
# A `pending` trace this old with an empty queue was never enqueued (or its
# job was dropped). With a non-empty queue it's just waiting its turn.
ORPHANED_PENDING_AFTER = timedelta(minutes=15)
_REQUEUE_BATCH = 200


async def recover_evaluations(
    session: AsyncSession, *, now: datetime | None = None
) -> dict[str, int]:
    now = now or datetime.now(UTC)
    has_evaluation = exists().where(Evaluation.trace_id == Trace.id)

    # 1. The job finished writing its result but died before flipping the status.
    finished: CursorResult = await session.execute(  # type: ignore[assignment]
        update(Trace)
        .where(Trace.evaluation_status.in_(("pending", "evaluating")), has_evaluation)
        .where(Trace.created_at < now - STUCK_EVALUATING_AFTER)
        .values(evaluation_status="completed")
        .execution_options(synchronize_session=False)
    )

    # 2. Claimed by a worker that never came back: hand it to the queue again.
    stuck_ids = (
        (
            await session.execute(
                select(Trace.id)
                .where(
                    Trace.evaluation_status == "evaluating",
                    Trace.created_at < now - STUCK_EVALUATING_AFTER,
                    ~has_evaluation,
                )
                .limit(_REQUEUE_BATCH)
            )
        )
        .scalars()
        .all()
    )
    if stuck_ids:
        await session.execute(
            update(Trace)
            .where(Trace.id.in_(stuck_ids), Trace.evaluation_status == "evaluating")
            .values(evaluation_status="pending")
            .execution_options(synchronize_session=False)
        )
    await session.commit()

    requeued = 0
    for trace_id in stuck_ids:
        await enqueue_evaluation(trace_id)
        requeued += 1

    # 3. Never enqueued at all. Only trust "nothing queued" when the queue is
    # actually empty — a backlog legitimately leaves old traces pending.
    orphaned = 0
    if await queue_depth() == 0:
        pending_ids = (
            (
                await session.execute(
                    select(Trace.id)
                    .where(
                        Trace.evaluation_status == "pending",
                        Trace.created_at < now - ORPHANED_PENDING_AFTER,
                        Trace.id.not_in(stuck_ids),  # just re-queued above
                        ~has_evaluation,
                    )
                    .order_by(Trace.created_at)
                    .limit(_REQUEUE_BATCH)
                )
            )
            .scalars()
            .all()
        )
        for trace_id in pending_ids:
            await enqueue_evaluation(trace_id)
            orphaned += 1

    counts = {"completed": finished.rowcount or 0, "requeued": requeued, "orphaned": orphaned}
    for kind, count in counts.items():
        if count:
            EVALUATION_RECOVERED_TOTAL.labels(kind=kind).inc(count)
    if any(counts.values()):
        logger.warning("evaluations_recovered", **counts)
    return counts
