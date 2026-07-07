"""Widen offices.whatsapp_token to Text for Fernet encryption at rest.

Revision ID: e5b7d3a1c9f2
Revises: d9f2c5a8b1e4
Create Date: 2026-07-06
"""
from alembic import op
import sqlalchemy as sa

revision = "e5b7d3a1c9f2"
down_revision = "d9f2c5a8b1e4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "offices",
        "whatsapp_token",
        existing_type=sa.String(length=500),
        type_=sa.Text(),
        existing_nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "offices",
        "whatsapp_token",
        existing_type=sa.Text(),
        type_=sa.String(length=500),
        existing_nullable=True,
    )
