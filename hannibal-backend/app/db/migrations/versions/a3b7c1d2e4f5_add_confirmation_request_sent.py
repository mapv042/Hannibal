"""add confirmation_request_sent

Revision ID: a3b7c1d2e4f5
Revises: 1429fa39bf5e
Create Date: 2026-04-07 10:00:00.000000

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'a3b7c1d2e4f5'
down_revision = '1429fa39bf5e'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'appointments',
        sa.Column('confirmation_request_sent', sa.Boolean(), server_default='false', nullable=False),
    )


def downgrade() -> None:
    op.drop_column('appointments', 'confirmation_request_sent')
