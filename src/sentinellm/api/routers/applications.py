from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from sentinellm.api.deps import RequireAdmin, RequireRead, get_db
from sentinellm.api.schemas.application import (
    APIKeyCreate,
    APIKeyCreated,
    APIKeyOut,
    ApplicationCreate,
    ApplicationOut,
    ApplicationUpdate,
)
from sentinellm.api.schemas.common import Page
from sentinellm.api.security import generate_api_key, hash_api_key, key_display_prefix
from sentinellm.db.models import APIKey, Application

router = APIRouter(prefix="/api/v1/applications", tags=["applications"])


@router.post(
    "",
    response_model=ApplicationOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(RequireAdmin)],
)
async def create_application(
    payload: ApplicationCreate, db: AsyncSession = Depends(get_db)
) -> ApplicationOut:
    app_row = Application(
        name=payload.name,
        description=payload.description,
        daily_cost_budget=payload.daily_cost_budget,
    )
    db.add(app_row)
    await db.flush()
    return ApplicationOut.model_validate(app_row)


@router.patch(
    "/{application_id}", response_model=ApplicationOut, dependencies=[Depends(RequireAdmin)]
)
async def update_application(
    application_id: str, payload: ApplicationUpdate, db: AsyncSession = Depends(get_db)
) -> ApplicationOut:
    row = await db.get(Application, application_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"application '{application_id}' not found")

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(row, field, value)

    await db.flush()
    return ApplicationOut.model_validate(row)


@router.get("", response_model=Page[ApplicationOut], dependencies=[Depends(RequireRead)])
async def list_applications(
    db: AsyncSession = Depends(get_db),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> Page[ApplicationOut]:
    total = (await db.execute(select(func.count()).select_from(Application))).scalar_one()
    rows = (
        (
            await db.execute(
                select(Application)
                .order_by(Application.created_at.desc())
                .limit(limit)
                .offset(offset)
            )
        )
        .scalars()
        .all()
    )
    return Page(
        items=[ApplicationOut.model_validate(r) for r in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post(
    "/api-keys",
    response_model=APIKeyCreated,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(RequireAdmin)],
)
async def create_api_key(
    payload: APIKeyCreate, db: AsyncSession = Depends(get_db)
) -> APIKeyCreated:
    """Returns the plaintext key exactly once. Only its SHA-256 digest is stored."""
    plaintext = generate_api_key()
    row = APIKey(
        application_id=payload.application_id,
        name=payload.name,
        role=payload.role,
        key_hash=hash_api_key(plaintext),
        key_prefix=key_display_prefix(plaintext),
    )
    db.add(row)
    await db.flush()
    return APIKeyCreated(
        id=row.id, name=row.name, role=row.role, key_prefix=row.key_prefix, plaintext_key=plaintext
    )


@router.get("/api-keys", response_model=Page[APIKeyOut], dependencies=[Depends(RequireRead)])
async def list_api_keys(
    db: AsyncSession = Depends(get_db),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> Page[APIKeyOut]:
    total = (await db.execute(select(func.count()).select_from(APIKey))).scalar_one()
    rows = (
        (
            await db.execute(
                select(APIKey).order_by(APIKey.created_at.desc()).limit(limit).offset(offset)
            )
        )
        .scalars()
        .all()
    )
    return Page(
        items=[APIKeyOut.model_validate(r) for r in rows], total=total, limit=limit, offset=offset
    )
