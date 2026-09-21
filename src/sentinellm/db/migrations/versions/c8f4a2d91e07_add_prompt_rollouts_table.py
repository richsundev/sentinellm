"""add prompt rollouts table

Revision ID: c8f4a2d91e07
Revises: c3a91d7e4b25
Create Date: 2026-09-21 12:00:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c8f4a2d91e07'
down_revision: Union[str, None] = 'c3a91d7e4b25'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('prompt_rollouts',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('application_id', sa.String(length=200), nullable=False),
    sa.Column('prompt_id', sa.String(length=200), nullable=False),
    sa.Column('incumbent_version', sa.Integer(), nullable=False),
    sa.Column('challenger_version', sa.Integer(), nullable=False),
    sa.Column('traffic_pct', sa.Float(), nullable=False),
    sa.Column('stage', sa.String(length=20), nullable=False),
    sa.Column('quality_floor', sa.Float(), nullable=False),
    sa.Column('max_quality_regression', sa.Float(), nullable=False),
    sa.Column('max_error_rate', sa.Float(), nullable=False),
    sa.Column('min_sample_size', sa.Integer(), nullable=False),
    sa.Column('step_pct', sa.Float(), nullable=False),
    sa.Column('max_pct', sa.Float(), nullable=False),
    sa.Column('last_evaluated_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('outcome_reason', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_prompt_rollouts_app_prompt_created', 'prompt_rollouts', ['application_id', 'prompt_id', 'created_at'], unique=False)
    op.create_index('uq_prompt_rollouts_one_active', 'prompt_rollouts', ['application_id', 'prompt_id'], unique=True, postgresql_where=sa.text("stage IN ('running', 'paused')"), sqlite_where=sa.text("stage IN ('running', 'paused')"))


def downgrade() -> None:
    op.drop_index('uq_prompt_rollouts_one_active', table_name='prompt_rollouts', postgresql_where=sa.text("stage IN ('running', 'paused')"), sqlite_where=sa.text("stage IN ('running', 'paused')"))
    op.drop_index('ix_prompt_rollouts_app_prompt_created', table_name='prompt_rollouts')
    op.drop_table('prompt_rollouts')
