from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from sentinellm.api.deps import RequireAdmin, RequireRead, get_db, scope_of
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


@router.post("", response_model=ApplicationOut, status_code=status.HTTP_201_CREATED)
async def create_application(
    payload: ApplicationCreate,
    db: AsyncSession = Depends(get_db),
    api_key: APIKey = Depends(RequireAdmin),
) -> ApplicationOut:
    if scope_of(api_key).ids is not None:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "A scoped API key cannot create other applications"
        )
    if (
        await db.execute(select(Application.id).where(Application.name == payload.name).limit(1))
    ).first() is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"application '{payload.name}' already exists"
        )
    app_row = Application(
        name=payload.name,
        description=payload.description,
        daily_cost_budget=payload.daily_cost_budget,
    )
    db.add(app_row)
    await db.flush()
    return ApplicationOut.model_validate(app_row)


@router.patch("/{application_id}", response_model=ApplicationOut)
async def update_application(
    application_id: str,
    payload: ApplicationUpdate,
    db: AsyncSession = Depends(get_db),
    api_key: APIKey = Depends(RequireAdmin),
) -> ApplicationOut:
    row = await db.get(Application, application_id)
    if row is None or not scope_of(api_key).contains(row.id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"application '{application_id}' not found")

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(row, field, value)

    await db.flush()
    return ApplicationOut.model_validate(row)


@router.get("", response_model=Page[ApplicationOut])
async def list_applications(
    db: AsyncSession = Depends(get_db),
    api_key: APIKey = Depends(RequireRead),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> Page[ApplicationOut]:
    stmt = select(Application)
    count_stmt = select(func.count()).select_from(Application)
    scope = scope_of(api_key)
    if scope.ids is not None:
        stmt = stmt.where(Application.id == api_key.application_id)
        count_stmt = count_stmt.where(Application.id == api_key.application_id)

    total = (await db.execute(count_stmt)).scalar_one()
    rows = (
        (await db.execute(stmt.order_by(Application.created_at.desc()).limit(limit).offset(offset)))
        .scalars()
        .all()
    )
    return Page(
        items=[ApplicationOut.model_validate(r) for r in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post("/api-keys", response_model=APIKeyCreated, status_code=status.HTTP_201_CREATED)
async def create_api_key(
    payload: APIKeyCreate,
    db: AsyncSession = Depends(get_db),
    api_key: APIKey = Depends(RequireAdmin),
) -> APIKeyCreated:
    """Returns the plaintext key exactly once. Only its SHA-256 digest is stored."""
    if not scope_of(api_key).contains(payload.application_id):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "A scoped API key cannot create keys for another application"
        )
    if scope_of(api_key).ids is not None and not payload.scoped_to_application:
        # A scoped key must never be able to mint an unscoped one for its own
        # application — that would hand the caller full cross-tenant access
        # (scoped_to_application defaults to False), defeating the whole
        # point of scoping.
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "A scoped API key can only create other scoped keys"
        )
    if await db.get(Application, payload.application_id) is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"application '{payload.application_id}' not found"
        )
    plaintext = generate_api_key()
    row = APIKey(
        application_id=payload.application_id,
        name=payload.name,
        role=payload.role,
        key_hash=hash_api_key(plaintext),
        key_prefix=key_display_prefix(plaintext),
        scoped_to_application=payload.scoped_to_application,
    )
    db.add(row)
    await db.flush()
    return APIKeyCreated(
        id=row.id,
        name=row.name,
        role=row.role,
        key_prefix=row.key_prefix,
        plaintext_key=plaintext,
        scoped_to_application=row.scoped_to_application,
    )


@router.get("/api-keys", response_model=Page[APIKeyOut])
async def list_api_keys(
    db: AsyncSession = Depends(get_db),
    api_key: APIKey = Depends(RequireRead),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> Page[APIKeyOut]:
    stmt = select(APIKey)
    count_stmt = select(func.count()).select_from(APIKey)
    scope = scope_of(api_key)
    if scope.ids is not None:
        stmt = stmt.where(APIKey.application_id == api_key.application_id)
        count_stmt = count_stmt.where(APIKey.application_id == api_key.application_id)

    total = (await db.execute(count_stmt)).scalar_one()
    rows = (
        (await db.execute(stmt.order_by(APIKey.created_at.desc()).limit(limit).offset(offset)))
        .scalars()
        .all()
    )
    return Page(
        items=[APIKeyOut.model_validate(r) for r in rows], total=total, limit=limit, offset=offset
    )
