"""add state welcome duration cost to offices

Revision ID: d5f8a2b3c6e7
Revises: 1cc02229472f
Create Date: 2026-05-13 12:00:00.000000

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd5f8a2b3c6e7'
down_revision = '1cc02229472f'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('offices', sa.Column('state', sa.String(length=100), nullable=True))
    op.add_column('offices', sa.Column('welcome_message', sa.String(length=2000), nullable=True))
    op.add_column('offices', sa.Column('new_patient_duration_min', sa.Integer(), nullable=False, server_default='30'))
    op.add_column('offices', sa.Column('returning_patient_duration_min', sa.Integer(), nullable=False, server_default='30'))
    op.add_column('offices', sa.Column('new_patient_cost', sa.String(length=100), nullable=True))
    op.add_column('offices', sa.Column('returning_patient_cost', sa.String(length=100), nullable=True))


def downgrade() -> None:
    op.drop_column('offices', 'returning_patient_cost')
    op.drop_column('offices', 'new_patient_cost')
    op.drop_column('offices', 'returning_patient_duration_min')
    op.drop_column('offices', 'new_patient_duration_min')
    op.drop_column('offices', 'welcome_message')
    op.drop_column('offices', 'state')
