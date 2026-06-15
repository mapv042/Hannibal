"""Core availability engine for appointment scheduling."""

from __future__ import annotations

from datetime import datetime, date, timedelta, time
from typing import List, Optional
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
from app.core.exceptions import GoogleCalendarError
from app.utils.dates import now_mx
from app.utils.logger import get_logger

logger = get_logger(__name__)


async def get_available_slots(
    office_id: UUID,
    date_: date,
    duration_min: int,
    db: AsyncSession,
    redis_client: aioredis.Redis,
) -> List[AvailableSlot]:
    """
    Get available appointment slots for a given date.

    Algorithm:
    1. Check Redis cache first (TTL 5 minutes)
    2. Get availability_schedules for that day of week
    3. Generate all possible slots based on start_time, end_time, appointment_duration_min, buffer_min
    4. Subtract existing appointments (scheduled/confirmed) for that day
    5. Subtract time_blocks overlapping that day
    6. Store in Redis cache
    7. Return available slots

    Args:
        office_id: Office ID
        date_: Date to check availability
        duration_min: Requested slot duration in minutes
        db: Database session
        redis_client: Redis client

    Returns:
        List of available slots
    """
    # Step 1: Check Redis cache
    cache_key = f"avail_cache:{office_id}:{date_}"
    try:
        cached = await redis_client.get(cache_key)
        if cached:
            cached_data = json.loads(cached)
            logger.info(
                "availability_cache_hit",
                office_id=str(office_id),
                date=str(date_),
            )
            # Filter by requested duration
            return [
                AvailableSlot(**slot)
                for slot in cached_data
                if (
                    datetime.fromisoformat(slot["end_time"])
                    - datetime.fromisoformat(slot["start_time"])
                ).total_seconds()
                / 60
                >= duration_min
            ]
    except Exception as e:
        logger.warning("cache_read_error", error=str(e))

    # Step 2: Get availability_schedules for day of week
    day_of_week = date_.weekday()  # 0=Mon, 6=Sun - we need to map to db convention
    db_day_of_week = (day_of_week + 1) % 7  # Convert: Mon=1, Sun=0

    schedules_result = await db.execute(
        select(AvailabilitySchedule).where(
            and_(
                AvailabilitySchedule.office_id == office_id,
                AvailabilitySchedule.day_of_week == db_day_of_week,
                AvailabilitySchedule.is_active == True,
            )
        )
    )
    schedules = schedules_result.scalars().all()

    if not schedules:
        logger.info(
            "no_schedules_for_date",
            office_id=str(office_id),
            date=str(date_),
        )
        return []

    # Step 3: Generate all possible slots
    all_slots = []
    for schedule in schedules:
        current_time = datetime.combine(date_, schedule.start_time)
        end_of_day = datetime.combine(date_, schedule.end_time)

        while current_time + timedelta(minutes=duration_min) <= end_of_day:
            slot_end = current_time + timedelta(minutes=duration_min)
            all_slots.append((current_time, slot_end))
            current_time += timedelta(minutes=duration_min + schedule.buffer_minutes)

    if not all_slots:
        return []

    # Step 4: Get existing appointments for that day
    day_start = datetime.combine(date_, time.min)
    day_end = datetime.combine(date_, time.max)

    appointments_result = await db.execute(
        select(Appointment).where(
            and_(
                Appointment.office_id == office_id,
                Appointment.start_datetime >= day_start,
                Appointment.start_datetime <= day_end,
                Appointment.status.in_(["scheduled", "confirmed"]),
            )
        )
    )
    appointments = appointments_result.scalars().all()
    appointment_times = [(a.start_datetime, a.end_datetime) for a in appointments]

    # Step 5: Get time_blocks for that day
    blocks_result = await db.execute(
        select(TimeBlock).where(
            and_(
                TimeBlock.office_id == office_id,
                or_(
                    and_(
                        TimeBlock.start_date <= day_end,
                        TimeBlock.end_date >= day_start,
                    ),
                ),
            )
        )
    )
    blocks = blocks_result.scalars().all()
    block_times = [(b.start_date, b.end_date) for b in blocks]

    # Step 5.5: Get Google Calendar busy periods (required if configured)
    google_busy_times = []
    office = await db.get(Office, office_id)
    if office and office.google_calendar_token:
        # Google Calendar is configured — freebusy query is mandatory
        busy_periods = await get_freebusy(
            office_id=office_id,
            time_min=day_start,
            time_max=day_end,
            db=db,
        )
        for period in busy_periods:
            busy_start = datetime.fromisoformat(period["start"].replace("Z", "+00:00")).replace(tzinfo=None)
            busy_end = datetime.fromisoformat(period["end"].replace("Z", "+00:00")).replace(tzinfo=None)
            google_busy_times.append((busy_start, busy_end))

        logger.info(
            "google_freebusy_applied",
            office_id=str(office_id),
            date=str(date_),
            busy_count=len(google_busy_times),
        )
    else:
        raise GoogleCalendarError(
            "Google Calendar is not configured for this office. "
            "Please connect Google Calendar before scheduling."
        )

    # Filter available slots
    available_slots = []
    for start, end in all_slots:
        # Check overlap with appointments
        has_appointment_overlap = any(
            not (end <= appt_start or start >= appt_end)
            for appt_start, appt_end in appointment_times
        )

        # Check overlap with time_blocks
        has_block_overlap = any(
            not (end <= block_start or start >= block_end)
            for block_start, block_end in block_times
        )

        # Check overlap with Google Calendar busy periods
        has_google_overlap = any(
            not (end <= busy_start or start >= busy_end)
            for busy_start, busy_end in google_busy_times
        )

        if not has_appointment_overlap and not has_block_overlap and not has_google_overlap:
            available_slots.append(AvailableSlot(start_time=start, end_time=end))

    # Step 6: Cache the result (5 minute TTL)
    try:
        cache_data = [
            {
                "start_time": slot.start_time.isoformat(),
                "end_time": slot.end_time.isoformat(),
            }
            for slot in available_slots
        ]
        await redis_client.setex(cache_key, 300, json.dumps(cache_data))
    except Exception as e:
        logger.warning("cache_write_error", error=str(e))

    logger.info(
        "availability_generated",
        office_id=str(office_id),
        date=str(date_),
        slots_count=len(available_slots),
    )

    return available_slots


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
