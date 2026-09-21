import asyncio
import os

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from sentinellm.core.locks import lock_key, singleton_lock

POSTGRES_URL = os.environ.get("SENTINEL_TEST_POSTGRES_URL")
requires_postgres = pytest.mark.skipif(
    not POSTGRES_URL,
    reason="set SENTINEL_TEST_POSTGRES_URL (postgresql+asyncpg://...) to run advisory-lock tests",
)


def test_lock_key_is_stable_and_fits_a_postgres_bigint() -> None:
    assert lock_key("rollout") == lock_key("rollout")
    assert -(2**63) <= lock_key("rollout") < 2**63


def test_lock_keys_differ_per_loop() -> None:
    names = ["regression", "alerting", "model_health", "rollout"]
    assert len({lock_key(n) for n in names}) == len(names)


@pytest.mark.asyncio
async def test_lock_is_a_noop_that_reports_acquired_on_sqlite() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with (
            singleton_lock("rollout", engine) as first,
            singleton_lock("rollout", engine) as second,
        ):
            assert first is True
            # Single-process database: nothing to exclude.
            assert second is True
    finally:
        await engine.dispose()


@pytest.fixture
async def pg_engines() -> tuple[AsyncEngine, AsyncEngine]:
    """Two independent engines = two 'replicas' with separate connections."""
    assert POSTGRES_URL
    a, b = create_async_engine(POSTGRES_URL), create_async_engine(POSTGRES_URL)
    yield a, b
    await a.dispose()
    await b.dispose()


@requires_postgres
@pytest.mark.asyncio
async def test_second_replica_cannot_take_a_held_lock(
    pg_engines: tuple[AsyncEngine, AsyncEngine],
) -> None:
    replica_a, replica_b = pg_engines
    async with singleton_lock("test-exclusion", replica_a) as a_has_it:
        assert a_has_it is True
        async with singleton_lock("test-exclusion", replica_b) as b_has_it:
            assert b_has_it is False


@requires_postgres
@pytest.mark.asyncio
async def test_lock_is_released_when_the_pass_finishes(
    pg_engines: tuple[AsyncEngine, AsyncEngine],
) -> None:
    replica_a, replica_b = pg_engines
    async with singleton_lock("test-release", replica_a) as a_has_it:
        assert a_has_it is True
    async with singleton_lock("test-release", replica_b) as b_has_it:
        assert b_has_it is True


@requires_postgres
@pytest.mark.asyncio
async def test_lock_is_released_even_if_the_guarded_work_raises(
    pg_engines: tuple[AsyncEngine, AsyncEngine],
) -> None:
    replica_a, replica_b = pg_engines
    with pytest.raises(RuntimeError):
        async with singleton_lock("test-raise", replica_a) as a_has_it:
            assert a_has_it is True
            raise RuntimeError("pass blew up")
    async with singleton_lock("test-raise", replica_b) as b_has_it:
        assert b_has_it is True


@requires_postgres
@pytest.mark.asyncio
async def test_different_loops_do_not_block_each_other(
    pg_engines: tuple[AsyncEngine, AsyncEngine],
) -> None:
    replica_a, replica_b = pg_engines
    async with (
        singleton_lock("test-loop-one", replica_a) as one,
        singleton_lock("test-loop-two", replica_b) as two,
    ):
        assert one is True
        assert two is True


@requires_postgres
@pytest.mark.asyncio
async def test_lock_dies_with_its_connection(
    pg_engines: tuple[AsyncEngine, AsyncEngine],
) -> None:
    """A crashed replica must not wedge the loop: Postgres drops a session
    advisory lock the moment its connection goes away. Simulated by killing
    the holder's backend from the outside, as a dead pod looks to Postgres."""
    replica_a, replica_b = pg_engines
    key = lock_key("test-crash")
    holder = singleton_lock("test-crash", replica_a)
    assert await holder.__aenter__() is True

    async with replica_b.connect() as admin:
        pid = (
            await admin.execute(
                text(
                    "SELECT pid FROM pg_locks WHERE locktype = 'advisory' AND granted "
                    "AND classid::bigint = :hi AND objid::bigint = :lo AND objsubid = 1"
                ),
                {"hi": (key >> 32) & 0xFFFFFFFF, "lo": key & 0xFFFFFFFF},
            )
        ).scalar_one()
        await admin.execute(text("SELECT pg_terminate_backend(:pid)"), {"pid": pid})

    # Backend termination is asynchronous: give Postgres a moment to reap it.
    reacquired = False
    for _ in range(50):
        async with singleton_lock("test-crash", replica_b) as got_it:
            reacquired = got_it
        if reacquired:
            break
        await asyncio.sleep(0.05)
    assert reacquired is True

    # The holder's own cleanup finds its connection gone; that must not raise.
    await holder.__aexit__(None, None, None)
