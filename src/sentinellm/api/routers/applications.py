from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from sentinellm.api.deps import RequireAdmin, RequireRead, get_db, scope_of
from sentinellm.api.schemas.application import (
    APIKeyCreate,
    APIKeyCreated,
    APIKeyOut,
    APIKeyRotate,
    ApplicationCreate,
    ApplicationOut,
    ApplicationUpdate,
    BudgetStatusOut,
)
from sentinellm.api.schemas.common import Page
from sentinellm.api.security import generate_api_key, hash_api_key, key_display_prefix
from sentinellm.core.logging import get_logger
from sentinellm.db.models import APIKey, Application
from sentinellm.services.budget import live_budget_status

router = APIRouter(prefix="/api/v1/applications", tags=["applications"])
logger = get_logger(__name__)


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
        budget_action=payload.budget_action,
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
        if field == "budget_action" and value is None:
            continue  # not clearable: it always has a value
        setattr(row, field, value)

    await db.flush()
    return ApplicationOut.model_validate(row)


@router.get("/{application_id}/budget", response_model=BudgetStatusOut)
async def get_application_budget(
    application_id: str, db: AsyncSession = Depends(get_db), api_key: APIKey = Depends(RequireRead)
) -> BudgetStatusOut:
    """Live (uncached) spend against the budget: trailing 24h, counting traces
    recorded under the application's id or its name."""
    row = await db.get(Application, application_id)
    if row is None or not scope_of(api_key).contains(row.id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"application '{application_id}' not found")
    budget = await live_budget_status(db, row)
    return BudgetStatusOut(
        application_id=row.id,
        daily_cost_budget=budget.budget,
        budget_action=budget.action,
        spent_24h=round(budget.spent, 6),
        remaining=None if budget.remaining is None else round(budget.remaining, 6),
        exceeded=budget.exceeded,
    )


@router.get("", response_model=Page[ApplicationOut])
async def list_applications(
    db: AsyncSession = Depends(get_db),
    api_key: APIKey = Depends(RequireRead),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0, le=2_147_483_647),
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
        expires_at=_expiry(payload.expires_in_days),
    )
    db.add(row)
    await db.flush()
    return _created(row, plaintext)


@router.get("/api-keys", response_model=Page[APIKeyOut])
async def list_api_keys(
    db: AsyncSession = Depends(get_db),
    api_key: APIKey = Depends(RequireRead),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0, le=2_147_483_647),
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


def _expiry(days: int | None) -> datetime | None:
    return datetime.now(UTC) + timedelta(days=days) if days else None


def _created(row: APIKey, plaintext: str) -> APIKeyCreated:
    return APIKeyCreated(
        id=row.id,
        name=row.name,
        role=row.role,
        key_prefix=row.key_prefix,
        plaintext_key=plaintext,
        scoped_to_application=row.scoped_to_application,
        expires_at=row.expires_at,
    )


async def _manageable_key(db: AsyncSession, actor: APIKey, key_id: str) -> APIKey:
    """The key `key_id`, if `actor` may manage it. A scoped admin only ever sees
    its own application's keys — for the rest, 404 rather than 403, so it can't
    tell which ids exist."""
    row = await db.get(APIKey, key_id)
    if row is None or not scope_of(actor).contains(row.application_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"API key '{key_id}' not found")
    return row


@router.post("/api-keys/{key_id}/revoke", response_model=APIKeyOut)
async def revoke_api_key(
    key_id: str, db: AsyncSession = Depends(get_db), api_key: APIKey = Depends(RequireAdmin)
) -> APIKeyOut:
    """Permanently disables a key. Idempotent. A key can't revoke itself — that
    is almost always a lockout, and `rotate` does what was meant."""
    row = await _manageable_key(db, api_key, key_id)
    if row.id == api_key.id:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "a key can't revoke itself — rotate it instead, or revoke it with another admin key",
        )
    if not row.revoked:
        row.revoked = True
        row.revoked_at = datetime.now(UTC)
        await db.flush()
        logger.warning("api_key_revoked", key_id=row.id, by_key_id=api_key.id)
    return APIKeyOut.model_validate(row)


@router.post(
    "/api-keys/{key_id}/rotate", response_model=APIKeyCreated, status_code=status.HTTP_201_CREATED
)
async def rotate_api_key(
    key_id: str,
    payload: APIKeyRotate,
    db: AsyncSession = Depends(get_db),
    api_key: APIKey = Depends(RequireAdmin),
) -> APIKeyCreated:
    """Issues a replacement (same application, role and scope) and retires the
    old key — at once, or after `grace_minutes` so clients can switch over. The
    new plaintext is returned exactly once."""
    old = await _manageable_key(db, api_key, key_id)
    if old.revoked:
        raise HTTPException(status.HTTP_409_CONFLICT, "a revoked key can't be rotated")

    plaintext = generate_api_key()
    replacement = APIKey(
        application_id=old.application_id,
        name=old.name,
        role=old.role,
        scoped_to_application=old.scoped_to_application,
        key_hash=hash_api_key(plaintext),
        key_prefix=key_display_prefix(plaintext),
        expires_at=_expiry(payload.expires_in_days),
    )
    db.add(replacement)

    now = datetime.now(UTC)
    if payload.grace_minutes > 0:
        lapse = now + timedelta(minutes=payload.grace_minutes)
        current = old.expires_at
        if current is not None and current.tzinfo is None:
            current = current.replace(tzinfo=UTC)
        old.expires_at = min(current, lapse) if current is not None else lapse
    else:
        old.revoked = True
        old.revoked_at = now
    await db.flush()
    logger.warning(
        "api_key_rotated", old_key_id=old.id, new_key_id=replacement.id, by_key_id=api_key.id
    )
    return _created(replacement, plaintext)
