from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from sentinellm.api.deps import RequireRead, get_db, scope_of
from sentinellm.api.schemas.common import Page
from sentinellm.api.schemas.trace import RoutingDecisionOut
from sentinellm.db.models import APIKey, RoutingDecision, Trace

router = APIRouter(prefix="/api/v1/routing", tags=["routing"])


@router.get("/decisions", response_model=Page[RoutingDecisionOut])
async def list_routing_decisions(
    db: AsyncSession = Depends(get_db),
    api_key: APIKey = Depends(RequireRead),
    limit: int = Query(default=25, ge=1, le=200),
    offset: int = Query(default=0, ge=0, le=2_147_483_647),
) -> Page[RoutingDecisionOut]:
    stmt = select(RoutingDecision).options(selectinload(RoutingDecision.trace))
    count_stmt = select(func.count()).select_from(RoutingDecision)

    scope = scope_of(api_key)
    if scope.ids is not None:
        # A routing decision belongs to whichever application its trace does.
        stmt = stmt.join(Trace, Trace.id == RoutingDecision.trace_id).where(
            Trace.application_id.in_(scope.ids)
        )
        count_stmt = count_stmt.join(Trace, Trace.id == RoutingDecision.trace_id).where(
            Trace.application_id.in_(scope.ids)
        )

    total = (await db.execute(count_stmt)).scalar_one()
    stmt = stmt.order_by(RoutingDecision.created_at.desc()).limit(limit).offset(offset)
    rows = (await db.execute(stmt)).unique().scalars().all()
    return Page(
        items=[RoutingDecisionOut.model_validate(r) for r in rows],
        total=total,
        limit=limit,
        offset=offset,
    )
