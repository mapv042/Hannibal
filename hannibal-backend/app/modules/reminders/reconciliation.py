"""Reconciliation task to ensure all reminders are sent."""

from __future__ import annotations

from datetime import datetime, timedelta, date
import asyncio

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import get_async_session_maker
from app.db.models import Appointment
from app.utils.logger import get_logger

logger = get_logger(__name__)


def reconcile_reminders():
    """
    Celery task that runs daily at 1 AM.

    Finds appointments for the next day without reminders sent.
    Sends missing reminders to ensure no patient is left without notification.

    This is a safety net in case scheduled reminders failed or appointments
    were created near reminder time.
    """
    asyncio.run(_reconcile_reminders_async())


async def _reconcile_reminders_async():
    """Async implementation of reminder reconciliation."""
    async with get_async_session_maker()() as db:
        try:
            from app.modules.reminders.scheduler import schedule_reminders

            today = date.today()
            tomorrow = today + timedelta(days=1)

            # Get all confirmed/scheduled appointments for tomorrow
            start_of_tomorrow = datetime.combine(tomorrow, datetime.min.time())
            end_of_tomorrow = datetime.combine(tomorrow, datetime.max.time())

            result = await db.execute(
                select(Appointment).where(
                    and_(
                        Appointment.start_time >= start_of_tomorrow,
                        Appointment.start_time <= end_of_tomorrow,
                        Appointment.status.in_(["scheduled", "confirmed"]),
                    )
                )
            )
            appointments = result.scalars().all()

            logger.info(
                "reconciliation_started",
                appointments_found=len(appointments),
            )

            for appointment in appointments:
                # Check if all reminders are scheduled/sent
                if (
                    not appointment.reminder_48h_sent
                    or not appointment.reminder_24h_sent
                    or not appointment.reminder_2h_sent
                ):
                    # Re-program reminders
                    logger.warning(
                        "missing_reminders_detected",
                        appointment_id=str(appointment.id),
                        has_48h=appointment.reminder_48h_sent,
                        has_24h=appointment.reminder_24h_sent,
                        has_2h=appointment.reminder_2h_sent,
                    )

                    schedule_reminders(appointment.id, appointment.start_time)

            logger.info(
                "reconciliation_completed",
                appointments_processed=len(appointments),
            )

        except Exception as e:
            logger.error(
                "error_reconcile_reminders",
                error=str(e),
            )


async def get_appointments_without_reminder(
    db: AsyncSession, days_ahead: int = 1
) -> list:
    """
    Get appointments without reminders scheduled.

    Args:
        db: Database session
        days_ahead: Number of days to look ahead

    Returns:
        List of appointments missing reminders
    """
    today = date.today()
    target_date = today + timedelta(days=days_ahead)

    start_of_day = datetime.combine(target_date, datetime.min.time())
    end_of_day = datetime.combine(target_date, datetime.max.time())

    result = await db.execute(
        select(Appointment).where(
            and_(
                Appointment.start_time >= start_of_day,
                Appointment.start_time <= end_of_day,
                Appointment.status.in_(["scheduled", "confirmed"]),
            )
        )
    )
    appointments = result.scalars().all()

    # Filter for appointments missing at least one reminder
    return [
        appt for appt in appointments
        if not appt.reminder_48h_sent
        or not appt.reminder_24h_sent
        or not appt.reminder_2h_sent
    ]
