"""drop time blocks that mirror our own appointment events

Inbound Google Calendar sync used to recognise only block events as its own,
so every cita's event came back as a TimeBlock(origin="google_calendar") over
the cita itself — a hard conflict that stopped the doctor from overbooking that
slot and showed a phantom block. Sync now matches citas by
Appointment.google_event_id; this removes the mirrors already stored.

Revision ID: d2e3f4a5b6c7
Revises: c1d2e3f4a5b6
"""

from typing import Sequence, Union

from alembic import op

revision: str = "d2e3f4a5b6c7"
down_revision: Union[str, None] = "c1d2e3f4a5b6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        DELETE FROM time_blocks tb
        USING appointments a
        WHERE tb.origin = 'google_calendar'
          AND tb.google_event_id IS NOT NULL
          AND a.office_id = tb.office_id
          AND a.google_event_id = tb.google_event_id
        """
    )


def downgrade() -> None:
    # The deleted rows were duplicates of appointment events; nothing to restore.
    pass
