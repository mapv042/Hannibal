"""Bidirectional synchronization between Hannibal appointments and Google Calendar."""

from __future__ import annotations

from uuid import UUID
from datetime import date, datetime
from typing import Optional

import redis.asyncio as aioredis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import MX_TIMEZONE
from app.db.models import Appointment, Office, TimeBlock, GoogleCalendarEvent
from app.modules.google_calendar.service import (
    create_calendar_event,
    update_calendar_event,
    delete_calendar_event,
    list_events_incremental,
    mark_event_cancelled,
)
from app.modules.scheduling.availability import invalidate_availability_cache
from app.core.exceptions import GoogleCalendarError
from app.utils.logger import get_logger

logger = get_logger(__name__)


def _parse_gcal_datetime(node: dict) -> tuple[datetime, bool]:
    """Parse a Google event start/end node into a tz-aware MX datetime.

    All-day events use {"date": "YYYY-MM-DD"} (the end date is exclusive, i.e.
    the day after the last blocked day); timed events use {"dateTime": ...}.
    Returns (datetime, is_all_day).
    """
    if node.get("date"):
        d = date.fromisoformat(node["date"])
        return datetime(d.year, d.month, d.day, tzinfo=MX_TIMEZONE), True
    dt = datetime.fromisoformat(node["dateTime"].replace("Z", "+00:00"))
    return dt.astimezone(MX_TIMEZONE), False


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


async def import_calendar_changes(
    office_id: UUID,
    db: AsyncSession,
    redis_client: aioredis.Redis,
) -> None:
    """Inbound sync: pull changes the doctor made directly in Google Calendar.

    Triggered by a watch-channel push (the push only says "something changed",
    so we fetch the delta via the incremental events list). External events are
    mirrored as ``TimeBlock(origin="google_calendar")`` so they show on the
    dashboard and are subtracted from availability; deletions / "free"
    (transparent) events remove the mirror block. Events Hannibal itself created
    (tracked in ``GoogleCalendarEvent``) are skipped to avoid a feedback loop.

    Booking safety against these events is already guaranteed by the live
    freebusy check in the availability engine; this keeps the cache fresh and
    the dashboard accurate.
    """
    try:
        office = await db.get(Office, office_id)
        if not office or not office.google_calendar_token:
            return

        items, next_token = await list_events_incremental(
            office_id, db, office.google_sync_token
        )

        affected_dates: set[date] = set()

        for event in items:
            event_id = event.get("id")
            if not event_id:
                continue

            # Skip events Hannibal created itself (avoid re-importing our own).
            own = (
                await db.execute(
                    select(GoogleCalendarEvent).where(
                        GoogleCalendarEvent.google_event_id == event_id
                    )
                )
            ).scalar_one_or_none()
            if own:
                continue

            existing = (
                await db.execute(
                    select(TimeBlock).where(
                        TimeBlock.google_event_id == event_id,
                        TimeBlock.origin == "google_calendar",
                    )
                )
            ).scalar_one_or_none()

            # Cancelled or "free" (transparent) events don't block the calendar.
            if event.get("status") == "cancelled" or event.get("transparency") == "transparent":
                if existing:
                    affected_dates.add(existing.start_date.astimezone(MX_TIMEZONE).date())
                    await db.delete(existing)
                continue

            start_node = event.get("start") or {}
            end_node = event.get("end") or {}
            if not (start_node and end_node):
                continue

            start_dt, all_day = _parse_gcal_datetime(start_node)
            end_dt, _ = _parse_gcal_datetime(end_node)
            summary = event.get("summary") or "Bloqueo de Google Calendar"

            if existing:
                existing.start_date = start_dt
                existing.end_date = end_dt
                existing.reason = summary
                existing.is_all_day = all_day
            else:
                db.add(
                    TimeBlock(
                        office_id=office_id,
                        start_date=start_dt,
                        end_date=end_dt,
                        reason=summary,
                        is_all_day=all_day,
                        origin="google_calendar",
                        google_event_id=event_id,
                    )
                )
            affected_dates.add(start_dt.date())

        # Persist the new sync token; keep the old one if Google didn't send one.
        office.google_sync_token = next_token or office.google_sync_token
        await db.commit()

        for d in affected_dates:
            await invalidate_availability_cache(office_id, d, redis_client)

        logger.info(
            "calendar_changes_imported",
            office_id=str(office_id),
            processed=len(items),
            affected_days=len(affected_dates),
        )

    except Exception as e:
        logger.error(
            "error_import_calendar_changes",
            office_id=str(office_id),
            error=str(e),
        )
