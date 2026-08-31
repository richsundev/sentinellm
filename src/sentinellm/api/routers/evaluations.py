from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from sentinellm.api.deps import RequireRead, get_db
from sentinellm.api.schemas.common import Page
from sentinellm.api.schemas.trace import EvaluationOut
from sentinellm.db.models import Evaluation, Trace

router = APIRouter(prefix="/api/v1/evaluations", tags=["evaluations"])

_LOAD_OPTS = (
    selectinload(Evaluation.trace),
    selectinload(Evaluation.metrics),
    selectinload(Evaluation.claims),
)


@router.get("", response_model=Page[EvaluationOut], dependencies=[Depends(RequireRead)])
async def list_evaluations(
    db: AsyncSession = Depends(get_db),
    limit: int = Query(default=25, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    trace_id: str | None = None,
) -> Page[EvaluationOut]:
    stmt = select(Evaluation).options(*_LOAD_OPTS)
    count_stmt = select(func.count()).select_from(Evaluation)
    if trace_id:
        stmt = stmt.join(Trace, Trace.id == Evaluation.trace_id).where(Trace.trace_id == trace_id)
        count_stmt = count_stmt.join(Trace, Trace.id == Evaluation.trace_id).where(
            Trace.trace_id == trace_id
        )

    total = (await db.execute(count_stmt)).scalar_one()
    stmt = stmt.order_by(Evaluation.created_at.desc()).limit(limit).offset(offset)
    rows = (await db.execute(stmt)).unique().scalars().all()
    return Page(
        items=[EvaluationOut.model_validate(r) for r in rows],
        total=total,
        limit=limit,
        offset=offset,
    )
