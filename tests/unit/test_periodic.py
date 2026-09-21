import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest
from prometheus_client import REGISTRY
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from sentinellm.worker.periodic import run_once, run_periodic


@pytest.fixture
def session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)


def _runs(loop: str, outcome: str) -> float:
    return (
        REGISTRY.get_sample_value(
            "sentinel_worker_loop_runs_total", {"loop": loop, "outcome": outcome}
        )
        or 0.0
    )


@asynccontextmanager
async def _held_elsewhere(_name: str) -> AsyncIterator[bool]:
    yield False


@asynccontextmanager
async def _acquired(_name: str) -> AsyncIterator[bool]:
    yield True


@asynccontextmanager
async def _lock_backend_down(_name: str) -> AsyncIterator[bool]:
    raise ConnectionError("database unreachable")
    yield True  # pragma: no cover


@pytest.mark.asyncio
async def test_successful_pass_is_counted_and_timestamped(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    calls: list[AsyncSession] = []

    async def task(session: AsyncSession) -> None:
        calls.append(session)

    outcome = await run_once("t_ok", task, session_factory=session_factory, lock=_acquired)

    assert outcome == "ok"
    assert len(calls) == 1
    assert _runs("t_ok", "ok") == 1
    last = REGISTRY.get_sample_value(
        "sentinel_worker_loop_last_success_timestamp_seconds", {"loop": "t_ok"}
    )
    assert last is not None and last > 0
    assert (
        REGISTRY.get_sample_value("sentinel_worker_loop_duration_seconds_count", {"loop": "t_ok"})
        == 1
    )


@pytest.mark.asyncio
async def test_a_failing_task_is_contained_and_counted(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async def task(_session: AsyncSession) -> None:
        raise RuntimeError("boom")

    outcome = await run_once("t_err", task, session_factory=session_factory, lock=_acquired)

    assert outcome == "error"
    assert _runs("t_err", "error") == 1
    # A failed pass must not look like a healthy one to a staleness alert.
    assert (
        REGISTRY.get_sample_value(
            "sentinel_worker_loop_last_success_timestamp_seconds", {"loop": "t_err"}
        )
        is None
    )


@pytest.mark.asyncio
async def test_pass_is_skipped_when_another_replica_holds_the_lock(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    ran = False

    async def task(_session: AsyncSession) -> None:
        nonlocal ran
        ran = True

    outcome = await run_once("t_skip", task, session_factory=session_factory, lock=_held_elsewhere)

    assert outcome == "skipped"
    assert ran is False
    assert _runs("t_skip", "skipped") == 1


@pytest.mark.asyncio
async def test_lock_backend_failure_does_not_escape_the_loop(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async def task(_session: AsyncSession) -> None:
        raise AssertionError("must not run without the lock")

    outcome = await run_once(
        "t_lockdown", task, session_factory=session_factory, lock=_lock_backend_down
    )

    assert outcome == "error"


@pytest.mark.asyncio
async def test_non_singleton_loops_never_touch_the_lock(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    ran = False

    async def task(_session: AsyncSession) -> None:
        nonlocal ran
        ran = True

    outcome = await run_once(
        "t_free",
        task,
        session_factory=session_factory,
        singleton=False,
        lock=_lock_backend_down,  # would error if it were consulted
    )

    assert outcome == "ok"
    assert ran is True


@pytest.mark.asyncio
async def test_run_periodic_repeats_until_stopped(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    stop = asyncio.Event()
    passes = 0

    async def task(_session: AsyncSession) -> None:
        nonlocal passes
        passes += 1
        if passes == 3:
            stop.set()

    await asyncio.wait_for(
        run_periodic(
            "t_loop",
            task,
            interval_s=0.01,
            stop_event=stop,
            session_factory=session_factory,
            lock=_acquired,
        ),
        timeout=5,
    )

    assert passes == 3


@pytest.mark.asyncio
async def test_run_periodic_survives_task_errors(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    stop = asyncio.Event()
    passes = 0

    async def task(_session: AsyncSession) -> None:
        nonlocal passes
        passes += 1
        if passes == 3:
            stop.set()
        raise RuntimeError("always failing")

    await asyncio.wait_for(
        run_periodic(
            "t_loop_err",
            task,
            interval_s=0.01,
            stop_event=stop,
            session_factory=session_factory,
            lock=_acquired,
        ),
        timeout=5,
    )

    assert passes == 3
    assert _runs("t_loop_err", "error") == 3


@pytest.mark.asyncio
async def test_run_periodic_stops_promptly_during_the_sleep(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    stop = asyncio.Event()

    async def task(_session: AsyncSession) -> None:
        return None

    runner = asyncio.create_task(
        run_periodic(
            "t_stop",
            task,
            interval_s=3600,
            stop_event=stop,
            session_factory=session_factory,
            lock=_acquired,
        )
    )
    await asyncio.sleep(0.05)
    stop.set()

    await asyncio.wait_for(runner, timeout=2)
