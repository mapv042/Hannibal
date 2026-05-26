"""drop waitlist table

Revision ID: f1a2b3c4d5e6
Revises: e7a1b4c9d2f3
Create Date: 2026-05-26

Removes the waiting-list feature (table + relationships). The model, enum and
endpoint were dropped from the codebase; this migration removes the table.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "f1a2b3c4d5e6"
down_revision: Union[str, None] = "e7a1b4c9d2f3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_table("waitlist")


def downgrade() -> None:
    op.create_table(
        "waitlist",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("office_id", sa.UUID(), nullable=False),
        sa.Column("patient_id", sa.UUID(), nullable=False),
        sa.Column("preferred_days", postgresql.ARRAY(sa.Integer()), nullable=True),
        sa.Column("preferred_time", sa.String(length=50), nullable=False),
        sa.Column("is_urgent", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["office_id"], ["offices.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["patient_id"], ["patients.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
