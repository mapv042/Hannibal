"""add per-office reminder_rules and day_before flag

Revision ID: b2c3d4e5f6a7
Revises: f1a2b3c4d5e6
Create Date: 2026-06-03 10:00:00.000000

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "b2c3d4e5f6a7"
down_revision = "f1a2b3c4d5e6"
branch_labels = None
depends_on = None


# Default reminder rules, kept in sync with app.core.constants.DEFAULT_REMINDER_RULES.
# (reminder_type, offset_minutes) — negative = before start, positive = after.
DEFAULT_RULES = [
    ("day_before", -1440),
    ("4h", -240),
    ("1h", -60),
    ("post_appointment", 120),
]


def upgrade() -> None:
    # 1. New per-office reminder configuration table
    op.create_table(
        "reminder_rules",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("office_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("reminder_type", sa.String(length=50), nullable=False),
        sa.Column("offset_minutes", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["office_id"], ["offices.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("office_id", "reminder_type", name="uq_reminder_rule_office_type"),
    )
    op.create_index(
        "ix_reminder_rules_office_id", "reminder_rules", ["office_id"], unique=False
    )

    # 2. Seed default rules for every existing office
    for reminder_type, offset_minutes in DEFAULT_RULES:
        op.execute(
            sa.text(
                """
                INSERT INTO reminder_rules (id, office_id, reminder_type, offset_minutes, enabled, created_at)
                SELECT gen_random_uuid(), o.id, :rtype, :offset, true, now()
                FROM offices o
                """
            ).bindparams(rtype=reminder_type, offset=offset_minutes)
        )

    # 3. Appointment idempotency flags: add day_before, drop morning + 15m
    op.add_column(
        "appointments",
        sa.Column("reminder_day_before_sent", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )
    op.drop_column("appointments", "reminder_morning_sent")
    op.drop_column("appointments", "reminder_15m_sent")


def downgrade() -> None:
    op.add_column(
        "appointments",
        sa.Column("reminder_15m_sent", sa.BOOLEAN(), server_default=sa.text("false"), nullable=False),
    )
    op.add_column(
        "appointments",
        sa.Column("reminder_morning_sent", sa.BOOLEAN(), server_default=sa.text("false"), nullable=False),
    )
    op.drop_column("appointments", "reminder_day_before_sent")

    op.drop_index("ix_reminder_rules_office_id", table_name="reminder_rules")
    op.drop_table("reminder_rules")
