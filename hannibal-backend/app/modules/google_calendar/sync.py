"""Bidirectional synchronization between Hannibal appointments and Google Calendar."""

from __future__ import annotations

from uuid import UUID
from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Appointment, TimeBlock, GoogleCalendarEvent
from app.modules.google_calendar.service import (
    create_calendar_event,
    update_calendar_event,
    delete_calendar_event,
    mark_event_cancelled,
)
from app.core.exceptions import GoogleCalendarError
from app.utils.logger import get_logger

logger = get_logger(__name__)


async def sync_appointment(
    appointment_id: UUID,
    office_id: UUID,
    db: AsyncSession,
) -> None:
    """
    Sync an appointment to Google Calendar (create or update).

    Args:
        appointment_id: Appointment ID
        office_id: Office ID
        db: Database session
    """
    try:
        appointment = await db.get(Appointment, appointment_id)
        if not appointment or appointment.office_id != office_id:
            logger.warning("appointment_not_found", appointment_id=str(appointment_id))
            return

        # Check if Google event already exists
        google_event_result = await db.execute(
            select(GoogleCalendarEvent).where(
                GoogleCalendarEvent.appointment_id == appointment_id
            )
        )
        google_event = google_event_result.scalar_one_or_none()

        if google_event:
            # Update existing event
            await update_calendar_event(
                office_id=office_id,
                google_event_id=google_event.google_event_id,
                title=f"Appointment - {appointment.patient.name or 'Patient'}",
                start_time=appointment.start_datetime,
                end_time=appointment.end_datetime,
                description=appointment.reason or "",
                db=db,
            )
            logger.info(
                "appointment_synced_updated",
                appointment_id=str(appointment_id),
                google_event_id=google_event.google_event_id,
            )
        else:
            # Create new event
            google_event_id = await create_calendar_event(
                office_id=office_id,
                title=f"Appointment - {appointment.patient.name or 'Patient'}",
                start_time=appointment.start_datetime,
                end_time=appointment.end_datetime,
                description=appointment.reason or "",
                db=db,
            )

            # Store in database
            google_event = GoogleCalendarEvent(
                office_id=office_id,
                appointment_id=appointment_id,
                google_event_id=google_event_id,
                title=f"Appointment - {appointment.patient.name or 'Patient'}",
                start_time=appointment.start_datetime,
                end_time=appointment.end_datetime,
                is_time_block=False,
            )
            db.add(google_event)
            await db.commit()

            logger.info(
                "appointment_synced_created",
                appointment_id=str(appointment_id),
                google_event_id=google_event_id,
            )

    except Exception as e:
        logger.error(
            "error_sync_appointment",
            appointment_id=str(appointment_id),
            office_id=str(office_id),
            error=str(e),
        )


async def cancel_appointment_in_calendar(
    appointment_id: UUID,
    office_id: UUID,
    db: AsyncSession,
) -> None:
    """
    Mark an appointment's Google Calendar event as cancelled (red + transparent).

    Unlike unsync_appointment which deletes the event, this keeps it visible
    but marks it red and frees the time slot for other appointments.

    Args:
        appointment_id: Appointment ID
        office_id: Office ID
        db: Database session
    """
    try:
        # First try GoogleCalendarEvent table
        google_event_result = await db.execute(
            select(GoogleCalendarEvent).where(
                GoogleCalendarEvent.appointment_id == appointment_id
            )
        )
        google_event = google_event_result.scalar_one_or_none()

        google_event_id = google_event.google_event_id if google_event else None

        # Fallback: check google_event_id directly on the Appointment record
        if not google_event_id:
            appointment = await db.get(Appointment, appointment_id)
            if appointment and appointment.google_event_id:
                google_event_id = appointment.google_event_id

        if not google_event_id:
            logger.warning(
                "google_event_not_found_for_cancel",
                appointment_id=str(appointment_id),
            )
            return

        await mark_event_cancelled(
            office_id=office_id,
            google_event_id=google_event_id,
            db=db,
        )

        logger.info(
            "appointment_cancelled_in_calendar",
            appointment_id=str(appointment_id),
            google_event_id=google_event_id,
        )

    except Exception as e:
        logger.error(
            "error_cancel_appointment_in_calendar",
            appointment_id=str(appointment_id),
            office_id=str(office_id),
            error=str(e),
        )


async def unsync_appointment(
    appointment_id: UUID,
    office_id: UUID,
    db: AsyncSession,
) -> None:
    """
    Remove appointment from Google Calendar.

    Args:
        appointment_id: Appointment ID
        office_id: Office ID
        db: Database session
    """
    try:
        google_event_result = await db.execute(
            select(GoogleCalendarEvent).where(
                GoogleCalendarEvent.appointment_id == appointment_id
            )
        )
        google_event = google_event_result.scalar_one_or_none()

        if not google_event:
            logger.warning("google_event_not_found", appointment_id=str(appointment_id))
            return

        await delete_calendar_event(
            office_id=office_id,
            google_event_id=google_event.google_event_id,
            db=db,
        )

        await db.delete(google_event)
        await db.commit()

        logger.info(
            "appointment_unsynced",
            appointment_id=str(appointment_id),
            google_event_id=google_event.google_event_id,
        )

    except Exception as e:
        logger.error(
            "error_unsync_appointment",
            appointment_id=str(appointment_id),
            office_id=str(office_id),
            error=str(e),
        )


async def sync_time_block(
    block_id: UUID,
    office_id: UUID,
    db: AsyncSession,
) -> None:
    """
    Sync a time block to Google Calendar.

    Args:
        block_id: Time block ID
        office_id: Office ID
        db: Database session
    """
    try:
        time_block = await db.get(TimeBlock, block_id)
        if not time_block or time_block.office_id != office_id:
            logger.warning("time_block_not_found", block_id=str(block_id))
            return

        google_event_result = await db.execute(
            select(GoogleCalendarEvent).where(
                GoogleCalendarEvent.appointment_id == None,
                GoogleCalendarEvent.google_event_id == time_block.google_event_id,
            )
        )
        google_event = google_event_result.scalar_one_or_none()

        if google_event:
            # Update existing event
            await update_calendar_event(
                office_id=office_id,
                google_event_id=google_event.google_event_id,
                title=f"Blocked - {time_block.reason or 'Not specified'}",
                start_time=time_block.start_date,
                end_time=time_block.end_date,
                db=db,
                all_day=time_block.is_all_day,
            )
            logger.info(
                "time_block_synced_updated",
                block_id=str(block_id),
                google_event_id=google_event.google_event_id,
            )
        else:
            # Create new event (only if origin is manual, not google_calendar)
            if time_block.origin == "manual":
                google_event_id = await create_calendar_event(
                    office_id=office_id,
                    title=f"Blocked - {time_block.reason or 'Not specified'}",
                    start_time=time_block.start_date,
                    end_time=time_block.end_date,
                    description=f"Type: {time_block.reason}",
                    db=db,
                    all_day=time_block.is_all_day,
                )

                google_event = GoogleCalendarEvent(
                    office_id=office_id,
                    google_event_id=google_event_id,
                    title=f"Blocked - {time_block.reason or 'Not specified'}",
                    start_date=time_block.start_date,
                    end_date=time_block.end_date,
                    is_block=True,
                )
                db.add(google_event)
                # Link the event back to the block so it can be updated/unsynced later
                time_block.google_event_id = google_event_id
                await db.commit()

                logger.info(
                    "time_block_synced_created",
                    block_id=str(block_id),
                    google_event_id=google_event_id,
                )

    except Exception as e:
        logger.error(
            "error_sync_time_block",
            block_id=str(block_id),
            office_id=str(office_id),
            error=str(e),
        )
        # Propagate so the caller can roll back the DB block — a block that
        # exists in the DB but not in Google Calendar is an inconsistency.
        raise


async def unsync_time_block(
    block_id: UUID,
    office_id: UUID,
    db: AsyncSession,
) -> None:
    """
    Remove time block from Google Calendar.

    Args:
        block_id: Time block ID
        office_id: Office ID
        db: Database session
    """
    try:
        time_block = await db.get(TimeBlock, block_id)
        if not time_block:
            logger.warning("time_block_not_found", block_id=str(block_id))
            return

        if time_block.google_event_id:
            await delete_calendar_event(
                office_id=office_id,
                google_event_id=time_block.google_event_id,
                db=db,
            )

            google_event_result = await db.execute(
                select(GoogleCalendarEvent).where(
                    GoogleCalendarEvent.google_event_id == time_block.google_event_id
                )
            )
            google_event = google_event_result.scalar_one_or_none()

            if google_event:
                await db.delete(google_event)
                await db.commit()

        logger.info(
            "time_block_unsynced",
            block_id=str(block_id),
        )

    except Exception as e:
        logger.error(
            "error_unsync_time_block",
            block_id=str(block_id),
            office_id=str(office_id),
            error=str(e),
        )
