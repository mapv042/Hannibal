"""CRUD operations for availability schedules."""

from __future__ import annotations

from datetime import time
from typing import List
from uuid import UUID

from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AvailabilitySchedule, Office
from app.modules.scheduling.schemas import AvailabilityScheduleItem
from app.core.exceptions import NotFoundError
from app.utils.logger import get_logger

logger = get_logger(__name__)


def _parse_time(time_str: str) -> time:
    """Parse HH:MM string to time object."""
    parts = time_str.split(":")
    return time(int(parts[0]), int(parts[1]))


async def bulk_upsert_schedules(
    office_id: UUID,
    user_id: UUID,
    schedules_data: List[AvailabilityScheduleItem],
    db: AsyncSession,
) -> List[AvailabilitySchedule]:
    """
    Replace all availability schedules for an office.

    Deletes existing schedules and inserts new ones.

    Args:
        office_id: Office ID
        user_id: User ID (for authorization)
        schedules_data: List of schedule items
        db: Database session

    Returns:
        List of created AvailabilitySchedule objects
    """
    # Verify office belongs to user
    office = await db.get(Office, office_id)
    if not office or office.user_id != user_id:
        raise NotFoundError("Office not found")

    # Delete existing schedules
    await db.execute(
        delete(AvailabilitySchedule).where(
            AvailabilitySchedule.office_id == office_id
        )
    )

    # Insert new schedules
    new_schedules = []
    for item in schedules_data:
        schedule = AvailabilitySchedule(
            office_id=office_id,
            day_of_week=item.day_of_week,
            start_time=_parse_time(item.start_time),
            end_time=_parse_time(item.end_time),
            appointment_duration_min=item.appointment_duration_min,
            buffer_minutes=item.buffer_minutes,
            is_active=True,
        )
        db.add(schedule)
        new_schedules.append(schedule)

    await db.commit()

    # Refresh to get IDs
    for s in new_schedules:
        await db.refresh(s)

    logger.info(
        "availability_schedules_upserted",
        office_id=str(office_id),
        count=len(new_schedules),
    )

    return new_schedules


async def get_schedules(
    office_id: UUID,
    user_id: UUID,
    db: AsyncSession,
) -> List[AvailabilitySchedule]:
    """
    Get all availability schedules for an office.

    Args:
        office_id: Office ID
        user_id: User ID (for authorization)
        db: Database session

    Returns:
        List of AvailabilitySchedule objects
    """
    # Verify office belongs to user
    office = await db.get(Office, office_id)
    if not office or office.user_id != user_id:
        raise NotFoundError("Office not found")

    result = await db.execute(
        select(AvailabilitySchedule)
        .where(AvailabilitySchedule.office_id == office_id)
        .order_by(AvailabilitySchedule.day_of_week, AvailabilitySchedule.start_time)
    )
    return result.scalars().all()
