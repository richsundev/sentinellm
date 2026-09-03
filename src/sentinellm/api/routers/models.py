from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from sentinellm.api.deps import RequireRead, RequireWrite, get_db
from sentinellm.api.schemas.common import Page
from sentinellm.api.schemas.model import ModelCreate, ModelOut, ModelUpdate
from sentinellm.db.models import ModelPricing
from sentinellm.routing.stats import DBModelStatsProvider

router = APIRouter(prefix="/api/v1/models", tags=["models"])


async def _to_out(db: AsyncSession, row: ModelPricing) -> ModelOut:
    stats = await DBModelStatsProvider(db).get_stats(row.id)
    return ModelOut(
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


@router.post(
    "",
    response_model=ModelOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(RequireWrite)],
)
async def create_model(payload: ModelCreate, db: AsyncSession = Depends(get_db)) -> ModelOut:
    if await db.get(ModelPricing, payload.id) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, f"model '{payload.id}' already exists")
    row = ModelPricing(
        id=payload.id,
        name=payload.name,
        provider=payload.provider,
        input_price_per_1k=payload.input_price_per_1k,
        output_price_per_1k=payload.output_price_per_1k,
        context_window=payload.context_window,
        quality_tier=payload.quality_tier,
        avg_latency_ms_prior=payload.avg_latency_ms_prior,
        status=payload.status,
    )
    db.add(row)
    await db.flush()
    return await _to_out(db, row)


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
    items = [await _to_out(db, row) for row in rows]
    return Page(items=items, total=total, limit=limit, offset=offset)


@router.patch("/{model_id}", response_model=ModelOut, dependencies=[Depends(RequireWrite)])
async def update_model(
    model_id: str, payload: ModelUpdate, db: AsyncSession = Depends(get_db)
) -> ModelOut:
    row = await db.get(ModelPricing, model_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"model '{model_id}' not found")

    updates = payload.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(row, field, value)

    await db.flush()
    return await _to_out(db, row)
