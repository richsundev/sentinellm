from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from sentinellm.api.deps import RequireRead, get_db
from sentinellm.api.schemas.common import Page
from sentinellm.api.schemas.experiment import ExperimentOut
from sentinellm.db.models import Experiment

router = APIRouter(prefix="/api/v1/experiments", tags=["experiments"])


@router.get("", response_model=Page[ExperimentOut], dependencies=[Depends(RequireRead)])
async def list_experiments(
    db: AsyncSession = Depends(get_db),
    limit: int = Query(default=25, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> Page[ExperimentOut]:
    total = (await db.execute(select(func.count()).select_from(Experiment))).scalar_one()
    stmt = select(Experiment).order_by(Experiment.created_at.desc()).limit(limit).offset(offset)
    rows = (await db.execute(stmt)).scalars().all()
    return Page(
        items=[ExperimentOut.model_validate(r) for r in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{experiment_id}", response_model=ExperimentOut, dependencies=[Depends(RequireRead)])
async def get_experiment(experiment_id: str, db: AsyncSession = Depends(get_db)) -> ExperimentOut:
    row = await db.get(Experiment, experiment_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"experiment '{experiment_id}' not found")
    return ExperimentOut.model_validate(row)
