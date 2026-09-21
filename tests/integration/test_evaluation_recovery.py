"""A job popped from Redis by a worker that then died, or never pushed because
Redis was down, used to leave its trace un-evaluated forever."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from sentinellm.db.models import Evaluation, Trace
from sentinellm.worker.tasks import evaluation_recovery
from sentinellm.worker.tasks.evaluation_recovery import recover_evaluations


class _FakeQueue:
    def __init__(self, depth: int = 0) -> None:
        self.depth = depth
        self.enqueued: list[str] = []

    async def enqueue(self, trace_id: str) -> None:
        self.enqueued.append(trace_id)

    async def queue_depth(self) -> int:
        return self.depth


@pytest.fixture
def queue(monkeypatch: pytest.MonkeyPatch) -> _FakeQueue:
    fake = _FakeQueue()
    monkeypatch.setattr(evaluation_recovery, "enqueue_evaluation", fake.enqueue)
    monkeypatch.setattr(evaluation_recovery, "queue_depth", fake.queue_depth)
    return fake


async def _trace(
    session: AsyncSession, name: str, *, status: str, age_minutes: float, evaluated: bool = False
) -> Trace:
    trace = Trace(
        trace_id=f"trc_{name}",
        request_id=f"req_{name}",
        application_id="app-1",
        model="mock:sentinel-flash",
        provider="mock",
        prompt="q",
        response="a",
        evaluation_status=status,
        created_at=datetime.now(UTC) - timedelta(minutes=age_minutes),
    )
    session.add(trace)
    await session.flush()
    if evaluated:
        session.add(Evaluation(trace_id=trace.id, overall_quality=0.9, hallucination_score=0.1))
    await session.commit()
    return trace


@pytest.mark.asyncio
async def test_trace_stuck_evaluating_is_reset_and_requeued(
    db_session: AsyncSession, queue: _FakeQueue
) -> None:
    stuck = await _trace(db_session, "stuck", status="evaluating", age_minutes=30)

    counts = await recover_evaluations(db_session)

    assert counts["requeued"] == 1
    assert queue.enqueued == [stuck.id]
    await db_session.refresh(stuck)
    assert stuck.evaluation_status == "pending"


@pytest.mark.asyncio
async def test_recently_claimed_trace_is_left_alone(
    db_session: AsyncSession, queue: _FakeQueue
) -> None:
    live = await _trace(db_session, "live", status="evaluating", age_minutes=1)

    counts = await recover_evaluations(db_session)

    assert counts == {"completed": 0, "requeued": 0, "orphaned": 0}
    assert queue.enqueued == []
    await db_session.refresh(live)
    assert live.evaluation_status == "evaluating"


@pytest.mark.asyncio
async def test_evaluation_written_but_status_never_flipped_is_marked_completed(
    db_session: AsyncSession, queue: _FakeQueue
) -> None:
    done = await _trace(db_session, "done", status="evaluating", age_minutes=30, evaluated=True)

    counts = await recover_evaluations(db_session)

    assert counts["completed"] == 1
    assert queue.enqueued == []  # already has a result: nothing to re-run
    await db_session.refresh(done)
    assert done.evaluation_status == "completed"


@pytest.mark.asyncio
async def test_pending_trace_that_was_never_enqueued_is_queued_when_queue_is_empty(
    db_session: AsyncSession, queue: _FakeQueue
) -> None:
    orphan = await _trace(db_session, "orphan", status="pending", age_minutes=60)
    await _trace(db_session, "fresh", status="pending", age_minutes=2)

    counts = await recover_evaluations(db_session)

    assert counts["orphaned"] == 1
    assert queue.enqueued == [orphan.id]


@pytest.mark.asyncio
async def test_old_pending_traces_are_not_requeued_while_the_queue_has_a_backlog(
    db_session: AsyncSession, queue: _FakeQueue
) -> None:
    """A busy queue legitimately leaves old traces pending; re-pushing them
    would double the backlog."""
    await _trace(db_session, "waiting", status="pending", age_minutes=60)
    queue.depth = 500

    counts = await recover_evaluations(db_session)

    assert counts["orphaned"] == 0
    assert queue.enqueued == []


@pytest.mark.asyncio
async def test_failed_traces_are_never_retried(db_session: AsyncSession, queue: _FakeQueue) -> None:
    """`failed` is a verdict (the pipeline raised), not a lost job."""
    failed = await _trace(db_session, "failed", status="failed", age_minutes=600)

    await recover_evaluations(db_session)

    assert queue.enqueued == []
    await db_session.refresh(failed)
    assert failed.evaluation_status == "failed"
