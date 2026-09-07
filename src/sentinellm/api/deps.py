"""FastAPI dependency providers: DB session, authenticated API key, RBAC."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

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
    result = await db.execute(
        select(APIKey).where(APIKey.key_hash == key_hash).options(selectinload(APIKey.application))
    )
    api_key = result.scalar_one_or_none()
    if api_key is None or api_key.revoked:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or revoked API key")

    api_key.last_used_at = utcnow()
    await db.flush()
    return api_key


@dataclass(frozen=True, slots=True)
class ApplicationScope:
    """`ids` is `None` for an unscoped key (sees/writes every application —
    the default, preserving all pre-scoping behavior) or the `{Application.id,
    Application.name}` pair a scoped key is restricted to. Both forms are
    checked because `Trace.application_id` is a free-form string set by the
    caller — the seed script uses the row's id, SDK examples use a human
    slug — not a declared foreign key (see `Trace.application_id` docstring
    context in `worker/tasks/alerting.py`).
    """

    ids: frozenset[str] | None

    def contains(self, application_id: str) -> bool:
        return self.ids is None or application_id in self.ids


def scope_of(api_key: APIKey) -> ApplicationScope:
    if not api_key.scoped_to_application:
        return ApplicationScope(ids=None)
    return ApplicationScope(ids=frozenset({api_key.application_id, api_key.application.name}))


def require_role(required: str):
    async def _checker(api_key: APIKey = Depends(get_current_api_key)) -> APIKey:
        if not role_satisfies(api_key.role, required):
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"Requires '{required}' role or higher")
        return api_key

    return _checker


RequireRead = require_role("read")
RequireWrite = require_role("write")
RequireAdmin = require_role("admin")
