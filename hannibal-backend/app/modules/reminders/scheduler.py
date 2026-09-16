"""When each of an office's reminders is due for a given appointment.

Pure arithmetic: no Celery, no database. `app.modules.reminders.tasks` sweeps
for due reminders every few minutes and dispatches them.

This used to enqueue one Celery task per reminder with a far-future `eta` at
booking time. That made the broker the system of record for "what still has to
be sent", which it is bad at: a worker restart dropped every task it was
holding, a redelivery sent the same reminder twice, and the whole thing needed a
60-day visibility timeout plus a nightly reconciliation job to paper over both.
The appointment row already knows its start time and which reminders it has
sent, so the schedule is derived from the database on every sweep instead.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from app.config import settings
from app.core.constants import ReminderType
from app.utils.logger import get_logger

logger = get_logger(__name__)

# Sentinel: the reminder cannot be placed inside the sending window at all.
SKIP = None

# Reminders that are not patient-facing, or whose whole definition is "at this
# exact moment", so the patient sending window does not apply to them.
UNCLAMPED_TYPES = frozenset({
    ReminderType.AT_TIME.value,
    ReminderType.DOCTOR_BRIEF.value,
})

# How late a reminder may still go out once its due time has passed. A sweep
# that resumes after downtime should catch up, not re-enact yesterday: asking
# "¿ya llegaste?" an hour after the cita started is noise, while a day-before
# reminder is still useful any time before the appointment.
AT_TIME_GRACE_MINUTES = 30
POST_APPOINTMENT_GRACE_HOURS = 6


def clamp_to_sending_window(run_at: datetime, start_local: datetime) -> datetime | None:
    """Move a reminder's send time into the patient-facing window.

    Rule 15 of the self-validation protocol: the assistant never messages a
    patient in the middle of the night. Offsets are relative to the appointment,
    so a 6h-before reminder for a 9:00 AM cita computes to 3:00 AM — correct
    arithmetic, unacceptable product behavior.

    A reminder that falls before the window opens is pushed forward to the
    opening; one that falls after it closes is pulled back to the closing. A
    reminder that can only be delivered after the appointment has already
    started is dropped (returns None) — the day-before reminder already covers
    that patient, and a "recordatorio" arriving mid-consultation is noise.
    """
    opens = run_at.replace(
        hour=settings.earliest_reminder_hour, minute=0, second=0, microsecond=0
    )
    closes = run_at.replace(
        hour=settings.latest_reminder_hour, minute=0, second=0, microsecond=0
    )

    if opens <= run_at <= closes:
        return run_at

    if run_at < opens:
        adjusted = opens
    else:
        # After hours. A reminder still belongs before its appointment, so pull
        # it back to tonight's closing; a follow-up moves to tomorrow morning.
        adjusted = closes if run_at < start_local else opens + timedelta(days=1)

    # Never let a "before" reminder slide past the appointment it announces.
    if run_at < start_local and adjusted >= start_local:
        return SKIP
    return adjusted


def due_at(
    reminder_type: str, offset_minutes: int, start_local: datetime
) -> datetime | None:
    """When this reminder should go out, or None if it can't be placed.

    `offset_minutes` is signed relative to the appointment start (negative =
    before). The result is in the same timezone as `start_local`.
    """
    run_at = start_local + timedelta(minutes=offset_minutes)
    if reminder_type in UNCLAMPED_TYPES:
        return run_at
    return clamp_to_sending_window(run_at, start_local)


def is_still_worth_sending(
    reminder_type: str,
    offset_minutes: int,
    start_local: datetime,
    now: datetime,
) -> bool:
    """Whether a reminder whose due time has passed should still be delivered.

    Keeps a delayed sweep from sending something that no longer makes sense,
    without silently dropping reminders that are merely late.
    """
    if reminder_type == ReminderType.AT_TIME.value:
        return now <= start_local + timedelta(minutes=AT_TIME_GRACE_MINUTES)
    if offset_minutes > 0:
        return now <= start_local + timedelta(
            minutes=offset_minutes + POST_APPOINTMENT_GRACE_HOURS * 60
        )
    # Everything announcing an appointment is worth sending until it starts.
    return now < start_local
