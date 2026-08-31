from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from sentinellm.api.deps import RequireRead, get_db
from sentinellm.api.schemas.common import Page
from sentinellm.api.schemas.trace import RoutingDecisionOut
from sentinellm.db.models import RoutingDecision

router = APIRouter(prefix="/api/v1/routing", tags=["routing"])


@router.get(
    "/decisions", response_model=Page[RoutingDecisionOut], dependencies=[Depends(RequireRead)]
)
async def list_routing_decisions(
    db: AsyncSession = Depends(get_db),
    limit: int = Query(default=25, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> Page[RoutingDecisionOut]:
    total = (await db.execute(select(func.count()).select_from(RoutingDecision))).scalar_one()
    stmt = (
        select(RoutingDecision)
        .options(selectinload(RoutingDecision.trace))
        .order_by(RoutingDecision.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    rows = (await db.execute(stmt)).unique().scalars().all()
    return Page(
        items=[RoutingDecisionOut.model_validate(r) for r in rows],
        total=total,
        limit=limit,
        offset=offset,
    )
