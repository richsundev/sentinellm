from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from sentinellm.api.deps import RequireRead, get_db
from sentinellm.api.schemas.common import Page
from sentinellm.api.schemas.model import ModelOut
from sentinellm.db.models import ModelPricing
from sentinellm.routing.stats import DBModelStatsProvider

router = APIRouter(prefix="/api/v1/models", tags=["models"])


@router.get("", response_model=Page[ModelOut], dependencies=[Depends(RequireRead)])
async def list_models(
    db: AsyncSession = Depends(get_db),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> Page[ModelOut]:
    total = (await db.execute(select(func.count()).select_from(ModelPricing))).scalar_one()
    rows = (
        (
            await db.execute(
                select(ModelPricing).order_by(ModelPricing.name).limit(limit).offset(offset)
            )
        )
        .scalars()
        .all()
    )
    stats_provider = DBModelStatsProvider(db)
    items = []
    for row in rows:
        stats = await stats_provider.get_stats(row.id)
        items.append(
            ModelOut(
                id=row.id,
                name=row.name,
                provider=row.provider,
                input_price_per_1k=row.input_price_per_1k,
                output_price_per_1k=row.output_price_per_1k,
                context_window=row.context_window,
                avg_quality=stats.predicted_quality if stats.sample_count > 0 else None,
                avg_latency_ms=stats.avg_latency_ms if stats.sample_count > 0 else None,
                status=row.status,
            )
        )
    return Page(items=items, total=total, limit=limit, offset=offset)
