"""Scheduler for reminder tasks using Celery."""

from __future__ import annotations

from datetime import datetime, timedelta, time
from typing import List, Tuple
from uuid import UUID
from zoneinfo import ZoneInfo

from app.config import settings
from app.utils.logger import get_logger

logger = get_logger(__name__)

MX_TZ = ZoneInfo("America/Mexico_City")

# Minimum gap between two reminders to avoid spamming
MIN_GAP_MINUTES = 15


def compute_reminder_schedule(
    start_datetime_local: datetime,
    earliest_hour: int = 8,
) -> List[Tuple[str, datetime]]:
    """
    Compute which reminders to send and when, applying quiet-hours logic.

    Rules:
    - Morning reminder: day of appointment at earliest_hour:00
    - 4h before, 1h before, 15m before
    - If a reminder falls before earliest_hour, it is skipped
      (the morning reminder already covers that slot)
    - If the appointment is before earliest_hour, skip the morning reminder
      but still send 15m-before if it falls at or after (earliest_hour - 1)
    - Never schedule two reminders within MIN_GAP_MINUTES of each other

    Returns list of (reminder_type, scheduled_datetime) sorted by time.
    """
    appt_date = start_datetime_local.date()
    earliest_time = datetime.combine(appt_date, time(earliest_hour, 0), tzinfo=start_datetime_local.tzinfo)

    # Raw reminder times
    candidates = [
        ("morning", earliest_time),
        ("4h", start_datetime_local - timedelta(hours=4)),
        ("1h", start_datetime_local - timedelta(hours=1)),
        ("15m", start_datetime_local - timedelta(minutes=15)),
    ]

    # Filter: morning only if it's before the appointment
    # For early appointments (before earliest_hour), skip morning
    if earliest_time >= start_datetime_local:
        candidates = [(t, dt) for t, dt in candidates if t != "morning"]

    # Filter: skip reminders that fall before the allowed window
    # 15m-before gets a special grace: allowed from (earliest_hour - 1)
    min_allowed = datetime.combine(appt_date, time(earliest_hour - 1, 0), tzinfo=start_datetime_local.tzinfo)
    filtered = []
    for rtype, rtime in candidates:
        if rtype == "morning":
            filtered.append((rtype, rtime))
        elif rtype == "15m":
            if rtime >= min_allowed:
                filtered.append((rtype, rtime))
        else:
            if rtime >= earliest_time:
                filtered.append((rtype, rtime))

    # Dedup: if a non-morning reminder lands at the same time as morning (within MIN_GAP),
    # keep only morning
    morning_time = None
    for rtype, rtime in filtered:
        if rtype == "morning":
            morning_time = rtime
            break

    if morning_time:
        filtered = [
            (rtype, rtime) for rtype, rtime in filtered
            if rtype == "morning"
            or abs((rtime - morning_time).total_seconds()) >= MIN_GAP_MINUTES * 60
        ]

    # Sort by time
    filtered.sort(key=lambda x: x[1])

    # Final dedup: remove any reminder too close to the previous one
    result = []
    for rtype, rtime in filtered:
        if result and (rtime - result[-1][1]).total_seconds() < MIN_GAP_MINUTES * 60:
            continue
        result.append((rtype, rtime))

    return result


def schedule_reminders(appointment_id: UUID, start_datetime: datetime) -> None:
    """
    Schedule day-of reminders + post-follow-up for an appointment.

    Args:
        appointment_id: Appointment ID
        start_datetime: Appointment datetime (timezone-aware)
    """
    from app.modules.reminders.tasks import (
        send_reminder_morning,
        send_reminder_4h,
        send_reminder_1h,
        send_reminder_15m,
        post_follow_up,
    )

    task_map = {
        "morning": send_reminder_morning,
        "4h": send_reminder_4h,
        "1h": send_reminder_1h,
        "15m": send_reminder_15m,
    }

    try:
        # Convert to Mexico City timezone for quiet-hours calculation
        start_local = start_datetime.astimezone(MX_TZ)
        schedule = compute_reminder_schedule(start_local, settings.earliest_reminder_hour)
        now = datetime.now(MX_TZ)

        for rtype, rtime in schedule:
            if rtime <= now:
                logger.info(
                    "reminder_skipped_past",
                    appointment_id=str(appointment_id),
                    reminder_type=rtype,
                    scheduled_time=rtime.isoformat(),
                )
                continue

            task = task_map[rtype]
            result = task.apply_async(
                args=[str(appointment_id)],
                eta=rtime,
            )
            logger.info(
                "reminder_scheduled",
                appointment_id=str(appointment_id),
                reminder_type=rtype,
                scheduled_time=rtime.isoformat(),
                task_id=result.id,
            )

        # Post follow-up: 2 hours after appointment
        follow_up_time = start_datetime + timedelta(hours=2)
        if follow_up_time > now:
            result = post_follow_up.apply_async(
                args=[str(appointment_id)],
                eta=follow_up_time,
            )
            logger.info(
                "scheduled_post_follow_up",
                appointment_id=str(appointment_id),
                task_id=result.id,
            )

    except Exception as e:
        logger.error(
            "error_scheduling_reminders",
            appointment_id=str(appointment_id),
            error=str(e),
        )


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
