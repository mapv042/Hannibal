"""Scheduler for reminder tasks using Celery."""

from __future__ import annotations

from datetime import datetime, timedelta
from uuid import UUID

from app.utils.logger import get_logger

logger = get_logger(__name__)


def schedule_reminders(appointment_id: UUID, start_time: datetime) -> None:
    """
    Schedule reminders for an appointment.

    Schedules:
    - 48 hours before: send_reminder_48h
    - 24 hours before: send_reminder_24h
    - 2 hours before: send_reminder_2h
    - 1 hour before (if not confirmed): check_confirmation
    - 2 hours after: post_follow_up

    Args:
        appointment_id: Appointment ID
        start_time: Appointment datetime
    """
    from app.modules.reminders.tasks import (
        send_reminder_48h,
        send_reminder_24h,
        send_reminder_2h,
        check_confirmation,
        post_follow_up,
    )

    try:
        # 48 hours before
        reminder_48h_time = start_time - timedelta(hours=48)
        if reminder_48h_time > datetime.now():
            task_48h = send_reminder_48h.apply_async(
                args=[str(appointment_id)],
                eta=reminder_48h_time,
            )
            logger.info(
                "scheduled_reminder_48h",
                appointment_id=str(appointment_id),
                task_id=task_48h.id,
            )

        # 24 hours before
        reminder_24h_time = start_time - timedelta(hours=24)
        if reminder_24h_time > datetime.now():
            task_24h = send_reminder_24h.apply_async(
                args=[str(appointment_id)],
                eta=reminder_24h_time,
            )
            logger.info(
                "scheduled_reminder_24h",
                appointment_id=str(appointment_id),
                task_id=task_24h.id,
            )

        # 2 hours before
        reminder_2h_time = start_time - timedelta(hours=2)
        if reminder_2h_time > datetime.now():
            task_2h = send_reminder_2h.apply_async(
                args=[str(appointment_id)],
                eta=reminder_2h_time,
            )
            logger.info(
                "scheduled_reminder_2h",
                appointment_id=str(appointment_id),
                task_id=task_2h.id,
            )

        # 1 hour before (check confirmation)
        check_confirm_time = start_time - timedelta(hours=1)
        if check_confirm_time > datetime.now():
            task_check = check_confirmation.apply_async(
                args=[str(appointment_id)],
                eta=check_confirm_time,
            )
            logger.info(
                "scheduled_check_confirmation",
                appointment_id=str(appointment_id),
                task_id=task_check.id,
            )

        # 2 hours after (follow-up)
        follow_up_time = start_time + timedelta(hours=2)
        task_follow_up = post_follow_up.apply_async(
            args=[str(appointment_id)],
            eta=follow_up_time,
        )
        logger.info(
            "scheduled_post_follow_up",
            appointment_id=str(appointment_id),
            task_id=task_follow_up.id,
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

    In a production setup, this would revoke Celery tasks.
    Currently just logs the action.

    Args:
        appointment_id: Appointment ID
    """
    logger.info(
        "cancel_reminders",
        appointment_id=str(appointment_id),
        note="Celery task revocation would be implemented here",
    )
