"""api key lifecycle (expiry, revocation time) and per-application budget action

Revision ID: d4b7e91a3c52
Revises: c8f4a2d91e07
Create Date: 2026-09-21 18:00:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd4b7e91a3c52'
down_revision: Union[str, None] = 'c8f4a2d91e07'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('api_keys', sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('api_keys', sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True))
    # Keys revoked before this migration have no recorded time; `created_at` is
    # the closest honest value we hold.
    op.execute("UPDATE api_keys SET revoked_at = created_at WHERE revoked = true")
    op.add_column(
        'applications',
        sa.Column('budget_action', sa.String(length=10), nullable=False, server_default='alert'),
    )


def downgrade() -> None:
    op.drop_column('applications', 'budget_action')
    op.drop_column('api_keys', 'expires_at')
    op.drop_column('api_keys', 'revoked_at')
