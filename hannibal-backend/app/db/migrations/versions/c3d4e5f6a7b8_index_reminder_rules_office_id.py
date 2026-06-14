"""add index on reminder_rules.office_id

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-06-14

The index already exists in the production database (it was created out-of-band
by an uncommitted migration). This migration records it in the chain so a
freshly-built database matches the model. ``if_not_exists`` makes it a no-op
where the index is already present.
"""

from __future__ import annotations

from alembic import op

# revision identifiers, used by Alembic.
revision = "c3d4e5f6a7b8"
down_revision = "b2c3d4e5f6a7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_reminder_rules_office_id",
        "reminder_rules",
        ["office_id"],
        unique=False,
        if_not_exists=True,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_reminder_rules_office_id",
        table_name="reminder_rules",
        if_exists=True,
    )
