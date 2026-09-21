"""semantic cache context key

Revision ID: c3a91d7e4b25
Revises: 5f0188256a91
Create Date: 2026-09-20 23:58:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c3a91d7e4b25'
down_revision: Union[str, None] = '5f0188256a91'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'semantic_cache_entries',
        sa.Column('context_key', sa.String(length=64), nullable=False, server_default=''),
    )
    # Existing entries were stored without knowing what context produced them,
    # so none can be trusted to answer a context-bearing request. They carry the
    # empty key, matching only requests that also had no system prompt/context.


def downgrade() -> None:
    op.drop_column('semantic_cache_entries', 'context_key')
