"""Progressive prompt-version canary rollouts: the operator-facing side of
`worker.tasks.prompt_rollout`. Mirrors `/api/v1/rollouts` (model canaries)."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import ColumnElement, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from sentinellm.api.deps import RequireRead, RequireWrite, get_db, scope_of
from sentinellm.api.schemas.common import Page
from sentinellm.api.schemas.prompt_rollout import (
    PromptRolloutCreate,
    PromptRolloutDetailOut,
    PromptRolloutOut,
)
from sentinellm.db.models import APIKey, PromptRollout
from sentinellm.services.prompt_rollouts import (
    PromptRolloutConflictError,
    PromptRolloutInputError,
    compute_prompt_arm_stats,
    create_prompt_rollout,
)

router = APIRouter(prefix="/api/v1/prompt-rollouts", tags=["prompt-rollouts"])


@router.post("", response_model=PromptRolloutOut, status_code=status.HTTP_201_CREATED)
async def create_prompt_rollout_endpoint(
    payload: PromptRolloutCreate,
    db: AsyncSession = Depends(get_db),
    api_key: APIKey = Depends(RequireWrite),
) -> PromptRolloutOut:
    if not scope_of(api_key).contains(payload.application_id):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "API key is scoped to a different application"
        )
    try:
        rollout = await create_prompt_rollout(db, payload)
    except PromptRolloutInputError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except PromptRolloutConflictError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    return PromptRolloutOut.model_validate(rollout)


@router.get("", response_model=Page[PromptRolloutOut])
async def list_prompt_rollouts(
    db: AsyncSession = Depends(get_db),
    api_key: APIKey = Depends(RequireRead),
    application_id: str | None = None,
    prompt_id: str | None = None,
    stage: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0, le=2_147_483_647),
) -> Page[PromptRolloutOut]:
    clauses: list[ColumnElement[bool]] = []
    scope = scope_of(api_key)
    if scope.ids is not None:
        clauses.append(PromptRollout.application_id.in_(scope.ids))
    if application_id:
        clauses.append(PromptRollout.application_id == application_id)
    if prompt_id:
        clauses.append(PromptRollout.prompt_id == prompt_id)
    if stage:
        clauses.append(PromptRollout.stage == stage)

    total = (
        await db.execute(select(func.count()).select_from(PromptRollout).where(*clauses))
    ).scalar_one()
    rows = (
        (
            await db.execute(
                select(PromptRollout)
                .where(*clauses)
                .order_by(PromptRollout.created_at.desc())
                .limit(limit)
                .offset(offset)
            )
        )
        .scalars()
        .all()
    )
    return Page(
        items=[PromptRolloutOut.model_validate(r) for r in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


async def _get_scoped(
    db: AsyncSession, api_key: APIKey, rollout_id: str, *, for_update: bool = False
) -> PromptRollout:
    # `for_update` serialises an operator action and a worker pass on the row.
    rollout = await db.get(PromptRollout, rollout_id, with_for_update=for_update)
    if rollout is None or not scope_of(api_key).contains(rollout.application_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"prompt rollout '{rollout_id}' not found")
    return rollout


@router.get("/{rollout_id}", response_model=PromptRolloutDetailOut)
async def get_prompt_rollout(
    rollout_id: str, db: AsyncSession = Depends(get_db), api_key: APIKey = Depends(RequireRead)
) -> PromptRolloutDetailOut:
    rollout = await _get_scoped(db, api_key, rollout_id)
    stats = {
        version: await compute_prompt_arm_stats(
            db,
            application_id=rollout.application_id,
            prompt_id=rollout.prompt_id,
            version=version,
            since=rollout.created_at,
        )
        for version in (rollout.incumbent_version, rollout.challenger_version)
    }
    return PromptRolloutDetailOut(
        **PromptRolloutOut.model_validate(rollout).model_dump(),
        incumbent_stats=stats[rollout.incumbent_version],
        challenger_stats=stats[rollout.challenger_version],
    )


@router.post("/{rollout_id}/pause", response_model=PromptRolloutOut)
async def pause_prompt_rollout(
    rollout_id: str, db: AsyncSession = Depends(get_db), api_key: APIKey = Depends(RequireWrite)
) -> PromptRolloutOut:
    rollout = await _get_scoped(db, api_key, rollout_id, for_update=True)
    if rollout.stage != "running":
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f"rollout is '{rollout.stage}', not running"
        )
    rollout.stage = "paused"
    await db.flush()
    return PromptRolloutOut.model_validate(rollout)


@router.post("/{rollout_id}/resume", response_model=PromptRolloutOut)
async def resume_prompt_rollout(
    rollout_id: str, db: AsyncSession = Depends(get_db), api_key: APIKey = Depends(RequireWrite)
) -> PromptRolloutOut:
    rollout = await _get_scoped(db, api_key, rollout_id, for_update=True)
    if rollout.stage != "paused":
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f"rollout is '{rollout.stage}', not paused"
        )
    rollout.stage = "running"
    await db.flush()
    return PromptRolloutOut.model_validate(rollout)


@router.post("/{rollout_id}/promote", response_model=PromptRolloutOut)
async def promote_prompt_rollout(
    rollout_id: str, db: AsyncSession = Depends(get_db), api_key: APIKey = Depends(RequireWrite)
) -> PromptRolloutOut:
    rollout = await _get_scoped(db, api_key, rollout_id, for_update=True)
    if rollout.stage not in ("running", "paused"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"rollout is already '{rollout.stage}'")
    rollout.stage = "promoted"
    rollout.traffic_pct = rollout.max_pct
    rollout.outcome_reason = "manually promoted by operator"
    rollout.last_evaluated_at = datetime.now(UTC)
    await db.flush()
    return PromptRolloutOut.model_validate(rollout)


@router.post("/{rollout_id}/rollback", response_model=PromptRolloutOut)
async def rollback_prompt_rollout(
    rollout_id: str, db: AsyncSession = Depends(get_db), api_key: APIKey = Depends(RequireWrite)
) -> PromptRolloutOut:
    rollout = await _get_scoped(db, api_key, rollout_id, for_update=True)
    if rollout.stage not in ("running", "paused"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"rollout is already '{rollout.stage}'")
    rollout.stage = "rolled_back"
    rollout.traffic_pct = 0.0
    rollout.outcome_reason = "manually rolled back by operator"
    rollout.last_evaluated_at = datetime.now(UTC)
    await db.flush()
    return PromptRolloutOut.model_validate(rollout)
