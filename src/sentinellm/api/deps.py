"""FastAPI dependency providers: DB session, authenticated API key, RBAC."""

from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sentinellm.api.security import hash_api_key, role_satisfies
from sentinellm.db.base import utcnow
from sentinellm.db.models import APIKey
from sentinellm.db.session import get_session


async def get_db() -> AsyncIterator[AsyncSession]:
    async for session in get_session():
        yield session
        await session.commit()


async def get_current_api_key(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    db: AsyncSession = Depends(get_db),
) -> APIKey:
    if not x_api_key:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing X-API-Key header")

    key_hash = hash_api_key(x_api_key)
    result = await db.execute(select(APIKey).where(APIKey.key_hash == key_hash))
    api_key = result.scalar_one_or_none()
    if api_key is None or api_key.revoked:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or revoked API key")

    api_key.last_used_at = utcnow()
    await db.flush()
    return api_key


def require_role(required: str):
    async def _checker(api_key: APIKey = Depends(get_current_api_key)) -> APIKey:
        if not role_satisfies(api_key.role, required):
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"Requires '{required}' role or higher")
        return api_key

    return _checker


RequireRead = require_role("read")
RequireWrite = require_role("write")
RequireAdmin = require_role("admin")
