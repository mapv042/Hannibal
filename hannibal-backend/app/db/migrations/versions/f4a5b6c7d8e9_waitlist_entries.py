"""waitlist entries (offer freed slots to people who wanted a sooner one)

A redesign of the waitlist dropped in f1a2b3c4d5e6: now a periodic sweep
offers a freed slot over WhatsApp and the patient's "sí" books it through the
normal booking path.

Revision ID: f4a5b6c7d8e9
Revises: e3f4a5b6c7d8
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "f4a5b6c7d8e9"
down_revision: Union[str, None] = "e3f4a5b6c7d8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "waitlist_entries",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("office_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("whatsapp_id", sa.String(length=50), nullable=False),
        sa.Column("patient_name", sa.String(length=255), nullable=False),
        sa.Column("reason", sa.String(length=500), nullable=False),
        sa.Column("intake_notes", sa.String(length=2000), nullable=True),
        sa.Column("part_of_day", sa.String(length=10), nullable=True),
        sa.Column("window_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("replaces_appointment_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("offered_slot", sa.DateTime(timezone=True), nullable=True),
        sa.Column("offered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("declined_slots", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("appointment_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["office_id"], ["offices.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["replaces_appointment_id"], ["appointments.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["appointment_id"], ["appointments.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_waitlist_entries_office_status", "waitlist_entries", ["office_id", "status"]
    )
    op.execute("ALTER TABLE waitlist_entries ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.drop_index("ix_waitlist_entries_office_status", table_name="waitlist_entries")
    op.drop_table("waitlist_entries")
