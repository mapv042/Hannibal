"""structured onboarding fields and the week/day/6h reminder cadence

Two changes that the onboarding rework depends on.

1. Onboarding used to flatten services, insurers, alarm symptoms and the
   assistant's persona into `offices.custom_prompt` as prose. The doctor could
   not get any of it back when re-entering the wizard, nothing could be queried
   for the dashboard, and two offices spelled the same insurer differently.
   Each now gets its own column, seeded in the wizard from a curated catalogue
   (app/core/catalogs.py). `custom_prompt` stays: it is still the free-text
   "instrucciones personalizadas" field in Settings, and existing offices have
   content in it.

2. The reminder cadence moves from 1 day / 4h / 1h to 1 week / 1 day / 6h —
   doctors with a full agenda need lead time, not a same-hour nudge. Existing
   offices are migrated in place, preserving whether they had reminders on at
   all. `reminder_4h_sent` / `reminder_1h_sent` are deliberately NOT dropped:
   they record what was already delivered to patients before the switch.

Revision ID: c6a3f18d7e95
Revises: b4d6e8f0a2c1
Create Date: 2026-09-12 12:00:00.000000

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'c6a3f18d7e95'
down_revision = 'b4d6e8f0a2c1'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- Doctor identity and the second doctor-channel number -------------
    op.add_column('offices', sa.Column('doctor_first_name', sa.String(length=100), nullable=True))
    op.add_column('offices', sa.Column('doctor_last_name', sa.String(length=100), nullable=True))
    op.add_column('offices', sa.Column('secondary_owner_phone', sa.String(length=20), nullable=True))

    # --- Assistant persona -------------------------------------------------
    op.add_column(
        'offices',
        sa.Column(
            'assistant_gender',
            sa.String(length=20),
            server_default='femenino',
            nullable=False,
        ),
    )

    # --- Structured onboarding data ---------------------------------------
    op.add_column('offices', sa.Column('services', postgresql.JSONB(), nullable=True))
    op.add_column('offices', sa.Column('accepts_insurance', sa.String(length=20), nullable=True))
    op.add_column('offices', sa.Column('insurances', postgresql.JSONB(), nullable=True))
    op.add_column('offices', sa.Column('emergency_symptoms', postgresql.JSONB(), nullable=True))
    op.add_column('offices', sa.Column('intake_questions', postgresql.JSONB(), nullable=True))

    # --- Intake answers reach the doctor's pre-consultation brief ---------
    op.add_column('appointments', sa.Column('intake_notes', sa.String(length=2000), nullable=True))

    # --- New reminder cadence ---------------------------------------------
    op.add_column(
        'appointments',
        sa.Column('reminder_week_before_sent', sa.Boolean(), server_default='false', nullable=False),
    )
    op.add_column(
        'appointments',
        sa.Column('reminder_6h_sent', sa.Boolean(), server_default='false', nullable=False),
    )

    # Carry each office's intent across the rename: the 6h reminder inherits
    # whether the office had the 4h one enabled, and the week-before one
    # inherits the day-before setting (the closest "plan ahead" signal we have).
    op.execute(
        """
        INSERT INTO reminder_rules (id, office_id, reminder_type, offset_minutes, enabled)
        SELECT gen_random_uuid(), r.office_id, '6h', -360, r.enabled
        FROM reminder_rules r
        WHERE r.reminder_type = '4h'
          AND NOT EXISTS (
              SELECT 1 FROM reminder_rules x
              WHERE x.office_id = r.office_id AND x.reminder_type = '6h'
          )
        """
    )
    op.execute(
        """
        INSERT INTO reminder_rules (id, office_id, reminder_type, offset_minutes, enabled)
        SELECT gen_random_uuid(), r.office_id, 'week_before', -10080, r.enabled
        FROM reminder_rules r
        WHERE r.reminder_type = 'day_before'
          AND NOT EXISTS (
              SELECT 1 FROM reminder_rules x
              WHERE x.office_id = r.office_id AND x.reminder_type = 'week_before'
          )
        """
    )
    # An office that had rows but no '4h' row still needs a 6h rule, otherwise
    # it silently ends up with fewer reminders than a freshly created office.
    op.execute(
        """
        INSERT INTO reminder_rules (id, office_id, reminder_type, offset_minutes, enabled)
        SELECT gen_random_uuid(), o.id, '6h', -360, true
        FROM offices o
        WHERE EXISTS (SELECT 1 FROM reminder_rules r WHERE r.office_id = o.id)
          AND NOT EXISTS (
              SELECT 1 FROM reminder_rules r
              WHERE r.office_id = o.id AND r.reminder_type = '6h'
          )
        """
    )
    op.execute(
        """
        INSERT INTO reminder_rules (id, office_id, reminder_type, offset_minutes, enabled)
        SELECT gen_random_uuid(), o.id, 'week_before', -10080, true
        FROM offices o
        WHERE EXISTS (SELECT 1 FROM reminder_rules r WHERE r.office_id = o.id)
          AND NOT EXISTS (
              SELECT 1 FROM reminder_rules r
              WHERE r.office_id = o.id AND r.reminder_type = 'week_before'
          )
        """
    )
    op.execute("DELETE FROM reminder_rules WHERE reminder_type IN ('4h', '1h')")


def downgrade() -> None:
    # Restore the old cadence, preserving each office's on/off intent.
    op.execute(
        """
        INSERT INTO reminder_rules (id, office_id, reminder_type, offset_minutes, enabled)
        SELECT gen_random_uuid(), r.office_id, '4h', -240, r.enabled
        FROM reminder_rules r
        WHERE r.reminder_type = '6h'
          AND NOT EXISTS (
              SELECT 1 FROM reminder_rules x
              WHERE x.office_id = r.office_id AND x.reminder_type = '4h'
          )
        """
    )
    op.execute(
        """
        INSERT INTO reminder_rules (id, office_id, reminder_type, offset_minutes, enabled)
        SELECT gen_random_uuid(), r.office_id, '1h', -60, r.enabled
        FROM reminder_rules r
        WHERE r.reminder_type = '6h'
          AND NOT EXISTS (
              SELECT 1 FROM reminder_rules x
              WHERE x.office_id = r.office_id AND x.reminder_type = '1h'
          )
        """
    )
    op.execute("DELETE FROM reminder_rules WHERE reminder_type IN ('week_before', '6h')")

    op.drop_column('appointments', 'reminder_6h_sent')
    op.drop_column('appointments', 'reminder_week_before_sent')
    op.drop_column('appointments', 'intake_notes')
    op.drop_column('offices', 'intake_questions')
    op.drop_column('offices', 'emergency_symptoms')
    op.drop_column('offices', 'insurances')
    op.drop_column('offices', 'accepts_insurance')
    op.drop_column('offices', 'services')
    op.drop_column('offices', 'assistant_gender')
    op.drop_column('offices', 'secondary_owner_phone')
    op.drop_column('offices', 'doctor_last_name')
    op.drop_column('offices', 'doctor_first_name')
