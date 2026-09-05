"""add booked_by_patient_id and arrival tracking to appointments

Two features land in the same table:

- `booked_by_patient_id` records who asked for the appointment, so the patient
  tools can let a parent cancel the appointment they booked for their child
  while still refusing an id that belongs to an unrelated patient (Rule 8).
- The arrival columns back the waiting-room check-in: at the appointment's
  start time the assistant asks the patient whether they've arrived, and the
  answer has to be queryable per appointment (dashboard, doctor context), which
  a Redis session keyed by whatsapp_id can't do.

Also seeds the `at_time` reminder rule for existing offices so the check-in is
on by default, matching a freshly created office.

Revision ID: b4d6e8f0a2c1
Revises: f7c1a9e42b83
Create Date: 2026-09-03 10:00:00.000000

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'b4d6e8f0a2c1'
down_revision = 'f7c1a9e42b83'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- Rule 8: who booked it -------------------------------------------
    op.add_column(
        'appointments',
        sa.Column('booked_by_patient_id', sa.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        'fk_appointments_booked_by_patient_id',
        'appointments',
        'patients',
        ['booked_by_patient_id'],
        ['id'],
        ondelete='SET NULL',
    )

    # --- Waiting-room check-in -------------------------------------------
    op.add_column(
        'appointments',
        sa.Column('arrival_check_sent', sa.Boolean(), server_default='false', nullable=False),
    )
    op.add_column(
        'appointments',
        sa.Column('arrival_status', sa.String(length=20), nullable=True),
    )
    op.add_column(
        'appointments',
        sa.Column('arrival_reported_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        'appointments',
        sa.Column('arrival_eta_minutes', sa.Integer(), nullable=True),
    )

    # --- Doctor notification toggle for arrivals --------------------------
    op.add_column(
        'offices',
        sa.Column('notify_arrival', sa.Boolean(), server_default='true', nullable=False),
    )

    # --- Seed the at_time reminder rule for existing offices --------------
    # Offices created from now on get it from DEFAULT_REMINDER_RULES; existing
    # ones only have rows for the four older types, and get_active_reminder_rules
    # falls back to the defaults only when an office has NO rows at all.
    op.execute(
        """
        INSERT INTO reminder_rules (id, office_id, reminder_type, offset_minutes, enabled)
        SELECT gen_random_uuid(), o.id, 'at_time', 0, true
        FROM offices o
        WHERE EXISTS (SELECT 1 FROM reminder_rules r WHERE r.office_id = o.id)
          AND NOT EXISTS (
              SELECT 1 FROM reminder_rules r
              WHERE r.office_id = o.id AND r.reminder_type = 'at_time'
          )
        """
    )


def downgrade() -> None:
    op.execute("DELETE FROM reminder_rules WHERE reminder_type = 'at_time'")
    op.drop_column('offices', 'notify_arrival')
    op.drop_column('appointments', 'arrival_eta_minutes')
    op.drop_column('appointments', 'arrival_reported_at')
    op.drop_column('appointments', 'arrival_status')
    op.drop_column('appointments', 'arrival_check_sent')
    op.drop_constraint(
        'fk_appointments_booked_by_patient_id', 'appointments', type_='foreignkey'
    )
    op.drop_column('appointments', 'booked_by_patient_id')
