"""Minimal Redis list-backed job queue.

A full Celery deployment is more machinery than a single-queue "evaluate this
trace" workload justifies (see docs/design-decisions.md — "Why a lightweight
async worker instead of Celery"). Redis `LPUSH`/`BRPOP` gives at-least-once
delivery with a blocking consumer and near-zero operational surface; the
worker's idempotent evaluation write (unique constraint on
`evaluations.trace_id`) absorbs the at-least-once duplicate-delivery risk.
"""

from __future__ import annotations

import json
from typing import Any

from redis.asyncio import Redis

from sentinellm.core.config import get_settings

EVALUATION_QUEUE_KEY = "sentinel:queue:evaluation"

_redis_client: Redis | None = None


def get_redis() -> Redis:
    global _redis_client
    if _redis_client is None:
        # socket_timeout must comfortably exceed the largest BRPOP blocking
        # timeout ever passed to dequeue_evaluation, or the client-side socket
        # read times out before Redis's own server-side blocking timeout
        # returns (observed as a spurious redis.exceptions.TimeoutError with
        # every consumer poll under real docker-compose networking).
        _redis_client = Redis.from_url(
            get_settings().redis_url,
            decode_responses=True,
            socket_timeout=30,
            socket_connect_timeout=10,
        )
    return _redis_client


async def enqueue_evaluation(trace_db_id: str) -> None:
    redis = get_redis()
    await redis.lpush(EVALUATION_QUEUE_KEY, json.dumps({"trace_id": trace_db_id}))


async def dequeue_evaluation(timeout: int = 5) -> str | None:
    redis = get_redis()
    result: Any = await redis.brpop([EVALUATION_QUEUE_KEY], timeout=timeout)
    if result is None:
        return None
    _key, payload = result
    data = json.loads(payload)
    return data["trace_id"]


async def queue_depth() -> int:
    redis = get_redis()
    return await redis.llen(EVALUATION_QUEUE_KEY)
