"""add doctor notification preferences to offices

Revision ID: b8e4f1a09c23
Revises: a1b2c3d4e5f6
Create Date: 2026-06-17 12:00:00.000000

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b8e4f1a09c23'
down_revision = 'a1b2c3d4e5f6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('offices', sa.Column('notify_new_appointment', sa.Boolean(), server_default=sa.text('true'), nullable=False))
    op.add_column('offices', sa.Column('notify_cancellation', sa.Boolean(), server_default=sa.text('true'), nullable=False))
    op.add_column('offices', sa.Column('notify_new_patient', sa.Boolean(), server_default=sa.text('true'), nullable=False))
    op.add_column('offices', sa.Column('notify_unconfirmed', sa.Boolean(), server_default=sa.text('true'), nullable=False))


def downgrade() -> None:
    op.drop_column('offices', 'notify_unconfirmed')
    op.drop_column('offices', 'notify_new_patient')
    op.drop_column('offices', 'notify_cancellation')
    op.drop_column('offices', 'notify_new_appointment')
