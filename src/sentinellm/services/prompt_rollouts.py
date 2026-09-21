"""Service logic for progressive prompt-version canary rollouts.

The prompt-side twin of `services.rollouts`: split from the router so
`services.generation` (the request path) and `worker.tasks.prompt_rollout` can
use it without importing anything router-layer.
"""

from __future__ import annotations

import random
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from sentinellm.api.schemas.prompt_rollout import PromptArmStats, PromptRolloutCreate
from sentinellm.db.models import PromptRollout, PromptVersion, Trace
from sentinellm.services.rollouts import ArmWindow, load_window


class PromptRolloutConflictError(ValueError):
    """The application already has an active rollout for this prompt."""


class PromptRolloutInputError(ValueError):
    """A rollout arm names a prompt version that doesn't exist."""


async def get_latest_prompt_rollout(
    session: AsyncSession, application_id: str, prompt_id: str
) -> PromptRollout | None:
    """The most recently created rollout of `prompt_id` for this application,
    whatever its stage — a terminal rollout keeps deciding which version the
    application is served until a newer one supersedes it."""
    stmt = (
        select(PromptRollout)
        .where(PromptRollout.application_id == application_id, PromptRollout.prompt_id == prompt_id)
        .order_by(PromptRollout.created_at.desc())
        .limit(1)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


def choose_arm(rollout: PromptRollout) -> tuple[int, str]:
    """(version to serve, "challenger" | "incumbent") for one request."""
    if random.random() < rollout.traffic_pct / 100.0:
        return rollout.challenger_version, "challenger"
    return rollout.incumbent_version, "incumbent"


async def create_prompt_rollout(
    session: AsyncSession, payload: PromptRolloutCreate
) -> PromptRollout:
    statuses: dict[int, str] = {}
    for version in (payload.incumbent_version, payload.challenger_version):
        status = (
            await session.execute(
                select(PromptVersion.status).where(
                    PromptVersion.prompt_id == payload.prompt_id, PromptVersion.version == version
                )
            )
        ).scalar_one_or_none()
        if status is None:
            raise PromptRolloutInputError(f"prompt '{payload.prompt_id}' v{version} not found")
        statuses[version] = status
    if statuses[payload.challenger_version] == "deprecated":
        raise PromptRolloutConflictError(
            f"challenger '{payload.prompt_id}' v{payload.challenger_version} is deprecated — "
            "the worker would roll it back on its first pass"
        )

    existing = await get_latest_prompt_rollout(session, payload.application_id, payload.prompt_id)
    if existing is not None and existing.stage in ("running", "paused"):
        raise PromptRolloutConflictError(
            f"application '{payload.application_id}' already has an active rollout of "
            f"'{payload.prompt_id}' ({existing.id}, stage={existing.stage}) — pause, promote, "
            "or roll it back first"
        )

    rollout = PromptRollout(
        application_id=payload.application_id,
        prompt_id=payload.prompt_id,
        incumbent_version=payload.incumbent_version,
        challenger_version=payload.challenger_version,
        traffic_pct=payload.initial_pct,
        quality_floor=payload.quality_floor,
        max_quality_regression=payload.max_quality_regression,
        max_error_rate=payload.max_error_rate,
        min_sample_size=payload.min_sample_size,
        step_pct=payload.step_pct,
        max_pct=payload.max_pct,
    )
    session.add(rollout)
    try:
        await session.flush()
    except IntegrityError as exc:
        # Two concurrent creates can both pass the check above; the partial
        # unique index is the real guarantee.
        raise PromptRolloutConflictError(
            f"application '{payload.application_id}' already has an active rollout of "
            f"'{payload.prompt_id}'"
        ) from exc
    return rollout


async def load_prompt_arm_window(
    session: AsyncSession,
    *,
    application_id: str,
    prompt_id: str,
    version: int,
    since: datetime,
    until: datetime | None = None,
) -> ArmWindow:
    return await load_window(
        session,
        [
            Trace.application_id == application_id,
            Trace.prompt_id == prompt_id,
            Trace.prompt_version == version,
        ],
        since=since,
        until=until,
    )


async def compute_prompt_arm_stats(
    session: AsyncSession,
    *,
    application_id: str,
    prompt_id: str,
    version: int,
    since: datetime,
) -> PromptArmStats:
    window = await load_prompt_arm_window(
        session, application_id=application_id, prompt_id=prompt_id, version=version, since=since
    )
    if not window.traces:
        return PromptArmStats(
            version=version,
            request_count=0,
            error_rate=0.0,
            avg_quality=None,
            avg_latency_ms=0.0,
            avg_cost=0.0,
        )
    quality = window.avg_quality
    n = window.request_count
    return PromptArmStats(
        version=version,
        request_count=n,
        error_rate=round(window.error_rate, 4),
        avg_quality=round(quality, 4) if quality is not None else None,
        avg_latency_ms=round(sum(t.latency_ms for t in window.traces) / n, 2),
        avg_cost=round(sum(t.estimated_cost for t in window.traces) / n, 6),
    )
