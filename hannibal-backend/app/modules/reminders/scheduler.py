"""Scheduler for reminder tasks using Celery.

Reminders are rule-driven: each office configures which reminders to send and
when via ReminderRule rows (see app.modules.reminders.rules). This module turns
those rules into Celery `eta` tasks for a concrete appointment.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Iterable, Tuple
from uuid import UUID
from zoneinfo import ZoneInfo

from app.config import settings
from app.core.constants import ReminderType
from app.utils.logger import get_logger

logger = get_logger(__name__)

MX_TZ = ZoneInfo("America/Mexico_City")

# Sentinel: the reminder cannot be placed inside the sending window at all.
SKIP = None


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

    `at_time` (offset 0) never reaches this function: the waiting-room check-in
    is defined as happening at the appointment's start time.
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


def schedule_reminders(
    appointment_id: UUID,
    start_datetime: datetime,
    rules: Iterable[Tuple[str, int]],
) -> None:
    """
    Schedule reminders for an appointment from a list of office rules.

    Args:
        appointment_id: Appointment ID
        start_datetime: Appointment datetime (timezone-aware)
        rules: Iterable of (reminder_type, offset_minutes), where offset_minutes
            is signed relative to the appointment start (negative = before).
    """
    # Local import to avoid a circular import (tasks imports this module's caller).
    from app.modules.reminders.tasks import (
        send_reminder_day_before,
        send_reminder_week_before,
        send_reminder_6h,
        send_arrival_check,
        post_follow_up,
    )

    task_map = {
        ReminderType.WEEK_BEFORE.value: send_reminder_week_before,
        ReminderType.DAY_BEFORE.value: send_reminder_day_before,
        ReminderType.SIX_HOURS.value: send_reminder_6h,
        ReminderType.AT_TIME.value: send_arrival_check,
        ReminderType.POST_APPOINTMENT.value: post_follow_up,
    }

    try:
        start_local = start_datetime.astimezone(MX_TZ)
        now = datetime.now(MX_TZ)

        for reminder_type, offset_minutes in rules:
            task = task_map.get(reminder_type)
            if task is None:
                logger.warning(
                    "reminder_unknown_type",
                    appointment_id=str(appointment_id),
                    reminder_type=reminder_type,
                )
                continue

            run_at = start_local + timedelta(minutes=offset_minutes)

            # The waiting-room check-in is defined as happening at the start
            # time; every other reminder is kept inside the sending window.
            if offset_minutes != 0:
                adjusted = clamp_to_sending_window(run_at, start_local)
                if adjusted is SKIP:
                    logger.info(
                        "reminder_skipped_window",
                        appointment_id=str(appointment_id),
                        reminder_type=reminder_type,
                        computed_time=run_at.isoformat(),
                    )
                    continue
                if adjusted != run_at:
                    logger.info(
                        "reminder_shifted_into_window",
                        appointment_id=str(appointment_id),
                        reminder_type=reminder_type,
                        computed_time=run_at.isoformat(),
                        scheduled_time=adjusted.isoformat(),
                    )
                run_at = adjusted

            if run_at <= now:
                logger.info(
                    "reminder_skipped_past",
                    appointment_id=str(appointment_id),
                    reminder_type=reminder_type,
                    scheduled_time=run_at.isoformat(),
                )
                continue

            result = task.apply_async(args=[str(appointment_id)], eta=run_at)
            logger.info(
                "reminder_scheduled",
                appointment_id=str(appointment_id),
                reminder_type=reminder_type,
                scheduled_time=run_at.isoformat(),
                task_id=result.id,
            )

    except Exception as e:
        logger.error(
            "error_scheduling_reminders",
            appointment_id=str(appointment_id),
            error=str(e),
        )


async def schedule_reminders_for_appointment(
    db,
    office_id: UUID,
    appointment_id: UUID,
    start_datetime: datetime,
) -> None:
    """Schedule all of an office's active reminders for a fresh appointment.

    Call this whenever an appointment is created or moved to a new slot; the
    daily reconciliation remains only as a safety net. Tasks are idempotent
    (per-type sent flags + FOR UPDATE), so double-scheduling is harmless.
    """
    # Local import: rules pulls DB models, scheduler stays importable from tasks.
    from app.modules.reminders.rules import get_active_reminder_rules

    rules = await get_active_reminder_rules(db, office_id)
    schedule_reminders(appointment_id, start_datetime, rules)


def cancel_reminders(appointment_id: UUID) -> None:
    """
    Cancel all scheduled reminders for an appointment.

    Tasks check appointment status before sending, so cancelled
    appointments will have their reminders skipped automatically.
    """
    logger.info(
        "cancel_reminders",
        appointment_id=str(appointment_id),
        note="Tasks will skip cancelled appointments via idempotency checks",
    )
