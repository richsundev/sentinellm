"""Cluster-wide singleton locks for periodic worker tasks.

The worker Deployment runs several replicas
(`infrastructure/kubernetes/worker-deployment.yaml`: 2, HPA up to 10) and
every replica runs every periodic loop. The evaluation consumer is safe to
run concurrently (Redis `BRPOP` + an idempotent claim), but the rollout,
alerting, regression and model-health loops are not: the rollout loop in
particular is a non-idempotent state machine (`traffic_pct += step_pct`), so
two replicas evaluating the same rollout in the same window would double-step
it and double-fire its alert.

`singleton_lock` serialises one *pass* of a named loop across every replica
with a Postgres session-level advisory lock. A replica that can't get the
lock skips that pass (another replica is already doing it); because the lock
is only held while a pass runs, a crashed leader never stalls the loop — the
database releases the lock the moment its connection dies.

The lock lives on its own dedicated connection rather than on the session
doing the work, because those sessions commit mid-pass and a pooled
connection can change underneath a session between statements, which would
strand a session-level lock on the wrong connection.

On non-Postgres databases (SQLite in the test suite / local demos) there is
only ever one process, so the lock is a no-op that always reports acquired.
"""

from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from sentinellm.core.logging import get_logger
from sentinellm.db.session import get_engine

logger = get_logger(__name__)


def lock_key(name: str) -> int:
    """A stable signed 64-bit key (Postgres advisory locks take a `bigint`).

    Derived from SHA-256 rather than `hash()`, which is salted per process and
    would give every replica a different key for the same loop.
    """
    digest = hashlib.sha256(f"sentinellm:{name}".encode()).digest()
    return int.from_bytes(digest[:8], "big", signed=True)


@asynccontextmanager
async def singleton_lock(name: str, engine: AsyncEngine | None = None) -> AsyncIterator[bool]:
    """Yields `True` if this process now holds the cluster-wide lock `name`
    (and must run the guarded work), `False` if another replica holds it.
    """
    engine = engine or get_engine()
    if engine.dialect.name != "postgresql":
        yield True
        return

    key = lock_key(name)
    async with engine.connect() as conn:
        acquired = bool(
            (await conn.execute(text("SELECT pg_try_advisory_lock(:key)"), {"key": key})).scalar()
        )
        try:
            yield acquired
        finally:
            if acquired:
                try:
                    await conn.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": key})
                except Exception:
                    # A lock we couldn't release must not go back into the pool
                    # still held — dropping the connection makes Postgres
                    # release it. That fully handles the failure, so it is
                    # logged rather than raised: the guarded pass itself
                    # succeeded and shouldn't be reported as failed.
                    logger.warning("singleton_lock_unlock_failed", lock=name, exc_info=True)
                    await conn.invalidate()
