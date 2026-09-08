from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import ColumnElement, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from sentinellm.api.deps import RequireRead, RequireWrite, get_db, scope_of
from sentinellm.api.schemas.common import Page
from sentinellm.api.schemas.rollout import RolloutCreate, RolloutDetailOut, RolloutOut
from sentinellm.db.models import APIKey, ModelRollout
from sentinellm.services.rollouts import RolloutConflictError, compute_arm_stats, create_rollout

router = APIRouter(prefix="/api/v1/rollouts", tags=["rollouts"])


@router.post("", response_model=RolloutOut, status_code=status.HTTP_201_CREATED)
async def create_rollout_endpoint(
    payload: RolloutCreate,
    db: AsyncSession = Depends(get_db),
    api_key: APIKey = Depends(RequireWrite),
) -> RolloutOut:
    if not scope_of(api_key).contains(payload.application_id):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "API key is scoped to a different application"
        )
    try:
        rollout = await create_rollout(db, payload)
    except RolloutConflictError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    return RolloutOut.model_validate(rollout)


@router.get("", response_model=Page[RolloutOut])
async def list_rollouts(
    db: AsyncSession = Depends(get_db),
    api_key: APIKey = Depends(RequireRead),
    application_id: str | None = None,
    stage: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> Page[RolloutOut]:
    clauses: list[ColumnElement[bool]] = []
    scope = scope_of(api_key)
    if scope.ids is not None:
        clauses.append(ModelRollout.application_id.in_(scope.ids))
    if application_id:
        clauses.append(ModelRollout.application_id == application_id)
    if stage:
        clauses.append(ModelRollout.stage == stage)

    total = (
        await db.execute(select(func.count()).select_from(ModelRollout).where(*clauses))
    ).scalar_one()
    stmt = (
        select(ModelRollout)
        .where(*clauses)
        .order_by(ModelRollout.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    rows = (await db.execute(stmt)).scalars().all()
    return Page(
        items=[RolloutOut.model_validate(r) for r in rows], total=total, limit=limit, offset=offset
    )


async def _get_scoped_rollout(db: AsyncSession, api_key: APIKey, rollout_id: str) -> ModelRollout:
    rollout = await db.get(ModelRollout, rollout_id)
    if rollout is None or not scope_of(api_key).contains(rollout.application_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"rollout '{rollout_id}' not found")
    return rollout


@router.get("/{rollout_id}", response_model=RolloutDetailOut)
async def get_rollout(
    rollout_id: str, db: AsyncSession = Depends(get_db), api_key: APIKey = Depends(RequireRead)
) -> RolloutDetailOut:
    rollout = await _get_scoped_rollout(db, api_key, rollout_id)
    incumbent_stats = await compute_arm_stats(
        db,
        application_id=rollout.application_id,
        model=rollout.incumbent_model,
        since=rollout.created_at,
    )
    challenger_stats = await compute_arm_stats(
        db,
        application_id=rollout.application_id,
        model=rollout.challenger_model,
        since=rollout.created_at,
    )
    return RolloutDetailOut(
        **RolloutOut.model_validate(rollout).model_dump(),
        incumbent_stats=incumbent_stats,
        challenger_stats=challenger_stats,
    )


@router.post("/{rollout_id}/pause", response_model=RolloutOut)
async def pause_rollout(
    rollout_id: str, db: AsyncSession = Depends(get_db), api_key: APIKey = Depends(RequireWrite)
) -> RolloutOut:
    rollout = await _get_scoped_rollout(db, api_key, rollout_id)
    if rollout.stage != "running":
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f"rollout is '{rollout.stage}', not running"
        )
    rollout.stage = "paused"
    await db.flush()
    return RolloutOut.model_validate(rollout)


@router.post("/{rollout_id}/resume", response_model=RolloutOut)
async def resume_rollout(
    rollout_id: str, db: AsyncSession = Depends(get_db), api_key: APIKey = Depends(RequireWrite)
) -> RolloutOut:
    rollout = await _get_scoped_rollout(db, api_key, rollout_id)
    if rollout.stage != "paused":
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f"rollout is '{rollout.stage}', not paused"
        )
    rollout.stage = "running"
    await db.flush()
    return RolloutOut.model_validate(rollout)


@router.post("/{rollout_id}/promote", response_model=RolloutOut)
async def promote_rollout(
    rollout_id: str, db: AsyncSession = Depends(get_db), api_key: APIKey = Depends(RequireWrite)
) -> RolloutOut:
    rollout = await _get_scoped_rollout(db, api_key, rollout_id)
    if rollout.stage not in ("running", "paused"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"rollout is already '{rollout.stage}'")
    rollout.stage = "promoted"
    rollout.traffic_pct = rollout.max_pct
    rollout.outcome_reason = "manually promoted by operator"
    rollout.last_evaluated_at = datetime.now(UTC)
    await db.flush()
    return RolloutOut.model_validate(rollout)


@router.post("/{rollout_id}/rollback", response_model=RolloutOut)
async def rollback_rollout(
    rollout_id: str, db: AsyncSession = Depends(get_db), api_key: APIKey = Depends(RequireWrite)
) -> RolloutOut:
    rollout = await _get_scoped_rollout(db, api_key, rollout_id)
    if rollout.stage not in ("running", "paused"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"rollout is already '{rollout.stage}'")
    rollout.stage = "rolled_back"
    rollout.traffic_pct = 0.0
    rollout.outcome_reason = "manually rolled back by operator"
    rollout.last_evaluated_at = datetime.now(UTC)
    await db.flush()
    return RolloutOut.model_validate(rollout)
