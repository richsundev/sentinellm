from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from sentinellm.api.deps import RequireRead, get_db
from sentinellm.api.schemas.alert import AlertOut, RegressionOut
from sentinellm.api.schemas.common import Page
from sentinellm.db.models import Alert, Regression

alerts_router = APIRouter(prefix="/api/v1/alerts", tags=["alerts"])
regressions_router = APIRouter(prefix="/api/v1/regressions", tags=["regressions"])


@alerts_router.get("", response_model=Page[AlertOut], dependencies=[Depends(RequireRead)])
async def list_alerts(
    db: AsyncSession = Depends(get_db),
    limit: int = Query(default=25, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> Page[AlertOut]:
    total = (await db.execute(select(func.count()).select_from(Alert))).scalar_one()
    stmt = select(Alert).order_by(Alert.timestamp.desc()).limit(limit).offset(offset)
    rows = (await db.execute(stmt)).scalars().all()
    return Page(
        items=[AlertOut.model_validate(r) for r in rows], total=total, limit=limit, offset=offset
    )


@regressions_router.get("", response_model=Page[RegressionOut], dependencies=[Depends(RequireRead)])
async def list_regressions(
    db: AsyncSession = Depends(get_db),
    limit: int = Query(default=25, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> Page[RegressionOut]:
    total = (await db.execute(select(func.count()).select_from(Regression))).scalar_one()
    stmt = select(Regression).order_by(Regression.detected_at.desc()).limit(limit).offset(offset)
    rows = (await db.execute(stmt)).scalars().all()
    return Page(
        items=[RegressionOut.model_validate(r) for r in rows],
        total=total,
        limit=limit,
        offset=offset,
    )
