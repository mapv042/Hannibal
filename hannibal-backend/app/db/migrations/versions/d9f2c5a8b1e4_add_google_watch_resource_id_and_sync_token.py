"""add google watch resource id and sync token to offices

Revision ID: d9f2c5a8b1e4
Revises: b8e4f1a09c23
Create Date: 2026-06-18 12:00:00.000000

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd9f2c5a8b1e4'
down_revision = 'b8e4f1a09c23'
branch_labels = None
depends_on = None


def _existing_columns(table_name: str) -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return {col['name'] for col in inspector.get_columns(table_name)}


def upgrade() -> None:
    existing = _existing_columns('offices')
    if 'google_watch_resource_id' not in existing:
        op.add_column('offices', sa.Column('google_watch_resource_id', sa.String(length=255), nullable=True))
    if 'google_sync_token' not in existing:
        op.add_column('offices', sa.Column('google_sync_token', sa.Text(), nullable=True))


def downgrade() -> None:
    existing = _existing_columns('offices')
    if 'google_sync_token' in existing:
        op.drop_column('offices', 'google_sync_token')
    if 'google_watch_resource_id' in existing:
        op.drop_column('offices', 'google_watch_resource_id')
