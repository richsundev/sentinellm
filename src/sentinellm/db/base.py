"""Declarative base + portable column helpers.

The platform targets PostgreSQL in production (docker-compose / k8s) but runs
its full test suite against SQLite so contributors never need a running
database to `pytest`. JSON columns and string primary keys are used instead of
Postgres-only types (JSONB, native UUID) to keep the schema portable; the
tradeoff is documented in docs/design-decisions.md.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import DateTime
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
