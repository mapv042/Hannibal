"""Single booking engine shared by the patient bot, the doctor bot and the dashboard.

Every path that creates an appointment goes through book_appointment(), so the
guarantees live in exactly one place: slot validation, the anti-race Redis
lock, the Google Calendar event, availability-cache invalidation and reminder
scheduling. Callers keep their own transaction semantics (the tool handlers
commit at end of turn; the dashboard service commits itself) — this function
only flushes.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

import redis.asyncio as aioredis
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Appointment, Office
from app.modules.google_calendar.service import create_calendar_event
from app.modules.reminders.scheduler import schedule_reminders_for_appointment
from app.modules.scheduling.availability import (
    check_slot_bookable,
    invalidate_availability_cache,
    lock_slot_temporarily,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)

LOCKED_SLOT_MESSAGE = (
    "Ese horario se está agendando por otra persona en este momento. "
    "Vuelve a consultar disponibilidad en unos segundos."
)


@dataclass
class BookingOutcome:
    """Result of a booking attempt.

    Exactly one of `appointment` / `error` is set. `conflict` marks errors
    that came from availability validation (vs. the transient lock error), so
    the doctor flow can offer its allow_conflict override only when it applies.
    """

    appointment: Optional[Appointment] = None
    error: Optional[str] = None
    conflict: bool = False


async def book_appointment(
    db: AsyncSession,
    office: Office,
    *,
    patient_id: uuid.UUID,
    start_dt: datetime,
    duration_min: int,
    reason: str,
    appt_type: Optional[str],
    gcal_title: str,
    gcal_description: str,
    redis_client: Optional[aioredis.Redis] = None,
    allow_conflict: bool = False,
    gcal_color_id: str = "9",
) -> BookingOutcome:
    """Validate, lock and create an appointment (plus GCal event, cache, reminders).

    The slot lock is deliberately NOT released on success — its 60s TTL covers
    the window until the caller's transaction commits; releasing earlier would
    let a concurrent booker pass the overlap check before this appointment is
    visible.
    """
    end_dt = start_dt + timedelta(minutes=duration_min)

    if not allow_conflict:
        conflict = await check_slot_bookable(office.id, start_dt, end_dt, db)
        if conflict:
            return BookingOutcome(error=conflict, conflict=True)

    if redis_client is not None:
        locked = await lock_slot_temporarily(office.id, start_dt, redis_client)
        if not locked:
            return BookingOutcome(error=LOCKED_SLOT_MESSAGE)

    # Google Calendar event (best-effort: a GCal hiccup must not block the booking)
    google_event_id = None
    if office.google_calendar_token:
        try:
            google_event_id = await create_calendar_event(
                office_id=office.id,
                title=gcal_title,
                start_time=start_dt,
                end_time=end_dt,
                description=gcal_description,
                db=db,
                color_id=gcal_color_id,
            )
        except Exception as e:
            logger.error("booking_gcal_failed", office_id=str(office.id), error=str(e))

    appointment = Appointment(
        id=uuid.uuid4(),
        office_id=office.id,
        patient_id=patient_id,
        start_datetime=start_dt,
        end_datetime=end_dt,
        duration_minutes=duration_min,
        type=appt_type,
        consultation_reason=reason,
        status="scheduled",
        google_event_id=google_event_id,
    )
    db.add(appointment)
    await db.flush()

    if redis_client is not None:
        try:
            await invalidate_availability_cache(office.id, start_dt.date(), redis_client)
        except Exception as e:
            logger.warning("booking_cache_invalidate_failed", error=str(e))

    await schedule_reminders_for_appointment(db, office.id, appointment.id, start_dt)

    logger.info(
        "appointment_booked",
        appointment_id=str(appointment.id),
        office_id=str(office.id),
        start=start_dt.isoformat(),
        allow_conflict=allow_conflict,
    )
    return BookingOutcome(appointment=appointment)
