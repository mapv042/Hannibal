"""Core availability engine for appointment scheduling."""

from __future__ import annotations

from datetime import datetime, date, timedelta, time
from typing import List, NamedTuple, Optional, Tuple
from uuid import UUID
import json

import redis.asyncio as aioredis
from sqlalchemy import select, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    AvailabilitySchedule,
    Appointment,
    TimeBlock,
    Office,
)
from app.modules.scheduling.schemas import AvailableSlot
from app.modules.google_calendar.service import get_freebusy
from app.core.constants import MX_TIMEZONE
from app.core.exceptions import GoogleCalendarError
from app.utils.dates import now_mx
from app.utils.logger import get_logger

logger = get_logger(__name__)


class DayAvailability(NamedTuple):
    """Result of computing a day's free slots.

    `has_schedule` distinguishes "no working hours configured for this weekday"
    (False) from "configured but fully booked" (empty slots, True), so callers
    can word their message correctly.
    """

    slots: List[AvailableSlot]
    has_schedule: bool


async def _collect_busy_ranges(
    office_id: UUID,
    day_start: datetime,
    day_end: datetime,
    db: AsyncSession,
    *,
    google_required: bool,
) -> List[Tuple[datetime, datetime]]:
    """All tz-aware busy intervals for a day: appointments + blocks + Google.

    Single source of truth for the naive/aware normalization that previously
    lived (and diverged) in three different places.
    """
    busy: List[Tuple[datetime, datetime]] = []

    # Existing appointments (scheduled/confirmed)
    appointments = (await db.execute(
        select(Appointment).where(
            and_(
                Appointment.office_id == office_id,
                Appointment.start_datetime >= day_start,
                Appointment.start_datetime <= day_end,
                Appointment.status.in_(["scheduled", "confirmed"]),
            )
        )
    )).scalars().all()
    for a in appointments:
        a_start = a.start_datetime
        a_end = a.end_datetime
        if a_start.tzinfo is None:
            a_start = a_start.replace(tzinfo=MX_TIMEZONE)
        if a_end is None:
            a_end = a_start + timedelta(minutes=a.duration_minutes or 30)
        elif a_end.tzinfo is None:
            a_end = a_end.replace(tzinfo=MX_TIMEZONE)
        busy.append((a_start, a_end))

    # Time blocks overlapping the day (vacations, manual blocks, GCal-synced)
    blocks = (await db.execute(
        select(TimeBlock).where(
            and_(
                TimeBlock.office_id == office_id,
                TimeBlock.start_date <= day_end,
                TimeBlock.end_date >= day_start,
            )
        )
    )).scalars().all()
    for b in blocks:
        b_start = b.start_date
        b_end = b.end_date
        if b_start.tzinfo is None:
            b_start = b_start.replace(tzinfo=MX_TIMEZONE)
        if b_end.tzinfo is None:
            b_end = b_end.replace(tzinfo=MX_TIMEZONE)
        busy.append((b_start, b_end))

    # Google Calendar busy periods
    office = await db.get(Office, office_id)
    if office and office.google_calendar_token:
        busy_periods = await get_freebusy(
            office_id=office_id, time_min=day_start, time_max=day_end, db=db,
        )
        for period in busy_periods:
            g_start = datetime.fromisoformat(period["start"].replace("Z", "+00:00")).astimezone(MX_TIMEZONE)
            g_end = datetime.fromisoformat(period["end"].replace("Z", "+00:00")).astimezone(MX_TIMEZONE)
            busy.append((g_start, g_end))
        logger.info("google_freebusy_applied", office_id=str(office_id), busy_count=len(busy_periods))
    elif google_required:
        # Dashboard/engine path requires a connected calendar before scheduling.
        raise GoogleCalendarError(
            "Google Calendar is not configured for this office. "
            "Please connect Google Calendar before scheduling."
        )

    return busy


async def compute_day_availability(
    office_id: UUID,
    date_: date,
    db: AsyncSession,
    *,
    slot_minutes: Optional[int] = None,
    redis_client: Optional[aioredis.Redis] = None,
    only_future: bool = False,
    google_required: bool = False,
) -> DayAvailability:
    """Single availability engine shared by the dashboard and both WhatsApp bots.

    All datetimes are tz-aware (Mexico City) so slots can be compared against
    appointment/block/Google intervals without naive-vs-aware errors.

    Args:
        slot_minutes: slot length to lay out; None uses each schedule's own
            appointment_duration_min (the configured grid the bots display).
        redis_client: when provided, read/write the 5-min availability cache.
        only_future: drop slots that already started (use for "today").
        google_required: raise GoogleCalendarError when no calendar is connected
            (dashboard behavior); the bots pass False and simply skip it.
    """
    # Schedules for that weekday (DB convention: Sun=0..Sat=6)
    db_day_of_week = (date_.weekday() + 1) % 7
    schedules = (await db.execute(
        select(AvailabilitySchedule).where(
            and_(
                AvailabilitySchedule.office_id == office_id,
                AvailabilitySchedule.day_of_week == db_day_of_week,
                AvailabilitySchedule.is_active == True,
            )
        )
    )).scalars().all()
    if not schedules:
        logger.info("no_schedules_for_date", office_id=str(office_id), date=str(date_))
        return DayAvailability([], has_schedule=False)

    # Cache (only when a client is provided; key is per office+date, slots are
    # filtered by the requested length on read).
    cache_key = f"avail_cache:{office_id}:{date_}"
    if redis_client is not None:
        try:
            cached = await redis_client.get(cache_key)
            if cached:
                cached_slots = [AvailableSlot(**s) for s in json.loads(cached)]
                if slot_minutes is not None:
                    cached_slots = [
                        s for s in cached_slots
                        if (s.end_time - s.start_time).total_seconds() / 60 >= slot_minutes
                    ]
                logger.info("availability_cache_hit", office_id=str(office_id), date=str(date_))
                return DayAvailability(cached_slots, has_schedule=True)
        except Exception as e:
            logger.warning("cache_read_error", error=str(e))

    # Candidate grid (tz-aware MX). Slot length is the requested one, or the
    # schedule's configured duration when not specified.
    candidates: List[Tuple[datetime, datetime]] = []
    for schedule in schedules:
        length = slot_minutes if slot_minutes is not None else schedule.appointment_duration_min
        step = length + schedule.buffer_minutes
        cursor = datetime.combine(date_, schedule.start_time, tzinfo=MX_TIMEZONE)
        end_of_day = datetime.combine(date_, schedule.end_time, tzinfo=MX_TIMEZONE)
        while cursor + timedelta(minutes=length) <= end_of_day:
            candidates.append((cursor, cursor + timedelta(minutes=length)))
            cursor += timedelta(minutes=step)

    if not candidates:
        return DayAvailability([], has_schedule=True)

    day_start = datetime.combine(date_, time.min, tzinfo=MX_TIMEZONE)
    day_end = datetime.combine(date_, time.max, tzinfo=MX_TIMEZONE)
    busy = await _collect_busy_ranges(office_id, day_start, day_end, db, google_required=google_required)

    now = now_mx()
    available: List[AvailableSlot] = []
    for start, end in candidates:
        if only_future and start <= now:
            continue
        if any(not (end <= b_start or start >= b_end) for b_start, b_end in busy):
            continue
        available.append(AvailableSlot(start_time=start, end_time=end))

    if redis_client is not None:
        try:
            cache_data = [
                {"start_time": s.start_time.isoformat(), "end_time": s.end_time.isoformat()}
                for s in available
            ]
            await redis_client.setex(cache_key, 300, json.dumps(cache_data))
        except Exception as e:
            logger.warning("cache_write_error", error=str(e))

    logger.info("availability_generated", office_id=str(office_id), date=str(date_), slots_count=len(available))
    return DayAvailability(available, has_schedule=True)


async def check_slot_bookable(
    office_id: UUID,
    start_dt: datetime,
    end_dt: datetime,
    db: AsyncSession,
) -> Optional[str]:
    """Validate that a concrete slot can be booked right now.

    Checks that the slot falls inside the office's working hours for that
    weekday and that it doesn't overlap existing appointments, time blocks, or
    Google Calendar busy periods. Google Calendar is best-effort (not required).

    Returns None when bookable, or a Spanish reason string when not — meant to
    be relayed to the user by the LLM or wrapped in SlotNotAvailableError.
    """
    date_ = start_dt.astimezone(MX_TIMEZONE).date()

    db_day_of_week = (date_.weekday() + 1) % 7
    schedules = (await db.execute(
        select(AvailabilitySchedule).where(
            and_(
                AvailabilitySchedule.office_id == office_id,
                AvailabilitySchedule.day_of_week == db_day_of_week,
                AvailabilitySchedule.is_active == True,  # noqa: E712
            )
        )
    )).scalars().all()
    if not schedules:
        return "No hay horario de atención configurado para ese día."

    in_working_hours = False
    for schedule in schedules:
        window_start = datetime.combine(date_, schedule.start_time, tzinfo=MX_TIMEZONE)
        window_end = datetime.combine(date_, schedule.end_time, tzinfo=MX_TIMEZONE)
        if start_dt >= window_start and end_dt <= window_end:
            in_working_hours = True
            break
    if not in_working_hours:
        return "El horario está fuera del horario de atención del consultorio."

    day_start = datetime.combine(date_, time.min, tzinfo=MX_TIMEZONE)
    day_end = datetime.combine(date_, time.max, tzinfo=MX_TIMEZONE)
    busy = await _collect_busy_ranges(
        office_id, day_start, day_end, db, google_required=False,
    )
    for b_start, b_end in busy:
        if not (end_dt <= b_start or start_dt >= b_end):
            return "El horario ya está ocupado por otra cita o bloqueo."

    return None


async def get_available_slots(
    office_id: UUID,
    date_: date,
    duration_min: int,
    db: AsyncSession,
    redis_client: aioredis.Redis,
) -> List[AvailableSlot]:
    """Available slots of length `duration_min` for a date (dashboard/engine).

    Thin wrapper over compute_day_availability that preserves the historical
    behavior: caches, requires Google Calendar, returns just the slot list.
    """
    result = await compute_day_availability(
        office_id,
        date_,
        db,
        slot_minutes=duration_min,
        redis_client=redis_client,
        google_required=True,
    )
    return result.slots


async def invalidate_availability_cache(
    office_id: UUID,
    date_: date,
    redis_client: aioredis.Redis,
) -> None:
    """
    Invalidate availability cache for a given date.

    Args:
        office_id: Office ID
        date_: Date to invalidate
        redis_client: Redis client
    """
    cache_key = f"avail_cache:{office_id}:{date_}"
    try:
        await redis_client.delete(cache_key)
        logger.info(
            "cache_invalidated",
            office_id=str(office_id),
            date=str(date_),
        )
    except Exception as e:
        logger.warning("cache_delete_error", error=str(e))


async def lock_slot_temporarily(
    office_id: UUID,
    start_time: datetime,
    redis_client: aioredis.Redis,
    ttl: int = 60,
) -> bool:
    """
    Temporarily lock a slot to prevent race conditions.

    Uses Redis SETNX for atomic operation.

    Args:
        office_id: Office ID
        start_time: Slot start time
        redis_client: Redis client
        ttl: Lock TTL in seconds (default 60)

    Returns:
        True if lock acquired, False if already locked
    """
    lock_key = f"slot_lock:{office_id}:{start_time.isoformat()}"
    try:
        result = await redis_client.set(
            lock_key, "1", nx=True, ex=ttl
        )
        if result:
            logger.info("slot_locked", office_id=str(office_id), slot=lock_key)
        return result is not None
    except Exception as e:
        logger.error("slot_lock_error", error=str(e))
        return False


async def release_slot_lock(
    office_id: UUID,
    start_time: datetime,
    redis_client: aioredis.Redis,
) -> None:
    """
    Release a temporary slot lock.

    Args:
        office_id: Office ID
        start_time: Slot start time
        redis_client: Redis client
    """
    lock_key = f"slot_lock:{office_id}:{start_time.isoformat()}"
    try:
        await redis_client.delete(lock_key)
        logger.info(
            "slot_unlocked", office_id=str(office_id), slot=lock_key
        )
    except Exception as e:
        logger.warning("slot_unlock_error", error=str(e))


async def get_upcoming_slots(
    office_id: UUID,
    days: int,
    db: AsyncSession,
    redis_client: aioredis.Redis,
) -> List[AvailableSlot]:
    """
    Get all available slots for the next N days.

    Args:
        office_id: Office ID
        days: Number of days to check (default 7)
        db: Database session
        redis_client: Redis client

    Returns:
        List of available slots sorted by date
    """
    all_slots = []
    today = now_mx().date()  # Mexico City date, not the server's UTC date

    for i in range(days):
        check_date = today + timedelta(days=i)
        slots = await get_available_slots(
            office_id=office_id,
            date_=check_date,
            duration_min=30,  # Default to 30 min
            db=db,
            redis_client=redis_client,
        )
        all_slots.extend(slots)

    logger.info(
        "upcoming_slots_generated",
        office_id=str(office_id),
        days=days,
        total_slots=len(all_slots),
    )

    return all_slots
