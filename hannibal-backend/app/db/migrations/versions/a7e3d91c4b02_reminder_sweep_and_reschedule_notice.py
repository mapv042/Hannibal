"""reminder sweep, doctor brief, reschedule notice

Supports three changes that landed together:

1. The day-before reminder absorbed the separate "confirmation request" job, so
   `confirmation_request_sent` is gone — `reminder_day_before_sent` is now the
   single flag for that one message.
2. A new `doctor_brief` reminder rule sends the doctor their pre-consultation
   brief shortly before each appointment, tracked by `doctor_brief_sent`.
3. The doctor is notified whenever an appointment moves, gated per office by
   `notify_reschedule`.

Also drops three columns nothing reads: the retired 4h/1h reminder flags and
`messages.is_doctor_echo`, whose detection was never implemented.

Revision ID: a7e3d91c4b02
Revises: c6a3f18d7e95
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a7e3d91c4b02"
down_revision: Union[str, None] = "c6a3f18d7e95"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "offices",
        sa.Column(
            "notify_reschedule", sa.Boolean(), server_default="true", nullable=False
        ),
    )
    op.add_column(
        "appointments",
        sa.Column(
            "doctor_brief_sent", sa.Boolean(), server_default="false", nullable=False
        ),
    )

    # Carry over what the old confirmation job already sent, so a patient who
    # received yesterday's confirmation request doesn't get the merged
    # day-before message on top of it.
    op.execute(
        """
        UPDATE appointments
        SET reminder_day_before_sent = true
        WHERE confirmation_request_sent = true
        """
    )

    op.drop_column("appointments", "confirmation_request_sent")
    op.drop_column("appointments", "reminder_4h_sent")
    op.drop_column("appointments", "reminder_1h_sent")
    op.drop_column("messages", "is_doctor_echo")

    # Seed the doctor brief for offices that already have explicit rules: they
    # never fall back to DEFAULT_REMINDER_RULES, so without this they would
    # silently never get one.
    op.execute(
        """
        INSERT INTO reminder_rules (id, office_id, reminder_type, offset_minutes, enabled)
        SELECT gen_random_uuid(), o.id, 'doctor_brief', -15, true
        FROM offices o
        WHERE EXISTS (SELECT 1 FROM reminder_rules r WHERE r.office_id = o.id)
          AND NOT EXISTS (
              SELECT 1 FROM reminder_rules r
              WHERE r.office_id = o.id AND r.reminder_type = 'doctor_brief'
          )
        """
    )


def downgrade() -> None:
    op.execute("DELETE FROM reminder_rules WHERE reminder_type = 'doctor_brief'")

    op.add_column(
        "messages",
        sa.Column("is_doctor_echo", sa.Boolean(), server_default="false", nullable=False),
    )
    op.add_column(
        "appointments",
        sa.Column("reminder_1h_sent", sa.Boolean(), server_default="false", nullable=False),
    )
    op.add_column(
        "appointments",
        sa.Column("reminder_4h_sent", sa.Boolean(), server_default="false", nullable=False),
    )
    op.add_column(
        "appointments",
        sa.Column(
            "confirmation_request_sent",
            sa.Boolean(),
            server_default="false",
            nullable=False,
        ),
    )
    op.drop_column("appointments", "doctor_brief_sent")
    op.drop_column("offices", "notify_reschedule")
