"""One bad job must not take the worker's other loops down with it."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

import pytest

from sentinellm.worker import main as worker_main


class _FakeSession:
    pass


@pytest.mark.asyncio
async def test_a_job_that_raises_does_not_kill_the_consumer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`process_evaluation_job` only guards the pipeline; claiming the trace is
    a database call that can raise (a dropped connection, a deadlock). That
    exception used to escape the loop, and `asyncio.gather` in `run()` then took
    every other worker loop down with it."""
    jobs = ["t-bad", "t-good", "t-good-2"]
    handled: list[str] = []
    stop = asyncio.Event()

    async def fake_dequeue(timeout: int = 5) -> str | None:
        if not jobs:
            stop.set()
            return None
        return jobs.pop(0)

    async def fake_process(session: object, pipeline: object, trace_id: str) -> bool:
        if trace_id == "t-bad":
            raise ConnectionError("connection reset by peer")
        handled.append(trace_id)
        return True

    @asynccontextmanager
    async def fake_session():
        yield _FakeSession()

    monkeypatch.setattr(worker_main, "dequeue_evaluation", fake_dequeue)
    monkeypatch.setattr(worker_main, "process_evaluation_job", fake_process)
    monkeypatch.setattr(worker_main, "get_evaluation_pipeline", lambda: object())
    monkeypatch.setattr(worker_main, "get_sessionmaker", lambda: fake_session)

    await asyncio.wait_for(worker_main.evaluation_consumer_loop(stop), timeout=10)

    assert handled == ["t-good", "t-good-2"]
