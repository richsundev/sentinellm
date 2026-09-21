"""Runner for the worker's periodic loops (regression detection, alert
evaluation, model health, canary rollouts, queue-depth sampling).

Each loop used to be its own copy of the same try/except/sleep skeleton.
Centralising it gives every loop, uniformly:

* cluster-wide mutual exclusion via `core.locks.singleton_lock` (so running
  several worker replicas can't double-apply a non-idempotent pass),
* a per-loop pass counter, duration histogram and last-success timestamp
  (so a stalled or failing loop is visible on `/metrics` instead of only in
  logs), and
* the guarantee that no exception — from the task *or* from the lock's own
  database round-trip — can kill the loop.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager, nullcontext

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from sentinellm.core.locks import singleton_lock
from sentinellm.core.logging import get_logger
from sentinellm.db.session import get_sessionmaker
from sentinellm.observability.metrics import (
    WORKER_LOOP_DURATION_SECONDS,
    WORKER_LOOP_LAST_SUCCESS_TIMESTAMP,
    WORKER_LOOP_RUNS_TOTAL,
)

logger = get_logger(__name__)

PeriodicTask = Callable[[AsyncSession], Awaitable[object]]
LockFactory = Callable[[str], AbstractAsyncContextManager[bool]]


async def run_once(
    name: str,
    task: PeriodicTask,
    *,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
    singleton: bool = True,
    lock: LockFactory = singleton_lock,
) -> str:
    """One pass of a periodic loop. Returns the outcome: "ok", "error", or
    "skipped" (another replica held the singleton lock)."""
    session_factory = session_factory or get_sessionmaker()
    started = time.perf_counter()
    outcome = "ok"
    try:
        guard: AbstractAsyncContextManager[bool] = lock(name) if singleton else nullcontext(True)
        async with guard as acquired:
            if not acquired:
                outcome = "skipped"
            else:
                async with session_factory() as session:
                    await task(session)
    except Exception:
        outcome = "error"
        logger.exception("periodic_task_failed", loop=name)

    WORKER_LOOP_RUNS_TOTAL.labels(loop=name, outcome=outcome).inc()
    if outcome == "ok":
        WORKER_LOOP_DURATION_SECONDS.labels(loop=name).observe(time.perf_counter() - started)
        WORKER_LOOP_LAST_SUCCESS_TIMESTAMP.labels(loop=name).set_to_current_time()
    return outcome


async def run_periodic(
    name: str,
    task: PeriodicTask,
    *,
    interval_s: float,
    stop_event: asyncio.Event,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
    singleton: bool = True,
    lock: LockFactory = singleton_lock,
) -> None:
    while not stop_event.is_set():
        await run_once(name, task, session_factory=session_factory, singleton=singleton, lock=lock)
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop_event.wait(), timeout=interval_s)
