"""arrival no-response alert and post-visit prompt timing

Two waiting-room changes from the ARGOS test round:
- The doctor now hears when a patient didn't answer the check-in. Its
  idempotency flag lives on the appointment like the reminder flags.
- The post-appointment message is now an invitation to book the next cita,
  sent 10 minutes after the cita ENDS (it used to be a follow-up 2h after the
  start). Rules still on the old default move to the new one; an office that
  chose another offset keeps it.

Revision ID: b8c9d0e1f2a3
Revises: a7b8c9d0e1f2
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b8c9d0e1f2a3"
down_revision: Union[str, None] = "a7b8c9d0e1f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "appointments",
        sa.Column(
            "arrival_no_response_sent", sa.Boolean(), server_default="false", nullable=False
        ),
    )
    op.execute(
        "UPDATE reminder_rules SET offset_minutes = 10 "
        "WHERE reminder_type = 'post_appointment' AND offset_minutes = 120"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE reminder_rules SET offset_minutes = 120 "
        "WHERE reminder_type = 'post_appointment' AND offset_minutes = 10"
    )
    op.drop_column("appointments", "arrival_no_response_sent")
