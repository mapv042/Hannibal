"""Service layer for appointment operations."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import List, Optional
from uuid import UUID

import redis.asyncio as aioredis
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Appointment, Patient
from app.modules.scheduling.schemas import CreateAppointmentRequest, UpdateAppointmentRequest
from app.modules.scheduling.availability import (
    invalidate_availability_cache,
    lock_slot_temporarily,
    release_slot_lock,
)
from app.core.exceptions import NotFoundError, SlotNotAvailableError
from app.utils.logger import get_logger

logger = get_logger(__name__)


async def create_appointment(
    data: CreateAppointmentRequest,
    office_id: UUID,
    db: AsyncSession,
    redis_client: aioredis.Redis,
) -> Appointment:
    """
    Create a new appointment.

    Steps:
    1. Validate patient exists
    2. Validate slot availability (double-check)
    3. Acquire temporary lock on slot
    4. Create appointment record
    5. Invalidate availability cache
    6. Schedule reminders (placeholder)
    7. Trigger Google Calendar sync (placeholder)
    8. Release slot lock

    Args:
        data: Appointment creation request
        office_id: Office ID
        db: Database session
        redis_client: Redis client

    Returns:
        Created Appointment object

    Raises:
        NotFoundError: If patient not found
        SlotNotAvailableError: If slot is not available
    """
    # Step 1: Validate patient exists
    patient_result = await db.execute(
        select(Patient).where(
            and_(
                Patient.id == data.patient_id,
                Patient.office_id == office_id,
            )
        )
    )
    patient = patient_result.scalar_one_or_none()
    if not patient:
        raise NotFoundError("Patient not found")

    # Step 2 & 3: Acquire lock on slot
    lock_acquired = await lock_slot_temporarily(
        office_id, data.start_time, redis_client
    )
    if not lock_acquired:
        raise SlotNotAvailableError("Slot is being booked by another user")

    try:
        # Step 4: Create appointment
        end_time = data.start_time + timedelta(minutes=data.duration_min)
        appointment = Appointment(
            office_id=office_id,
            patient_id=data.patient_id,
            start_time=data.start_time,
            end_time=end_time,
            duration_min=data.duration_min,
            appointment_type=data.appointment_type,
            consultation_reason=data.consultation_reason,
            status="scheduled",
        )

        db.add(appointment)
        await db.flush()  # Get the ID without committing

        # Step 5: Invalidate cache
        await invalidate_availability_cache(
            office_id, data.start_time.date(), redis_client
        )

        await db.commit()
        await db.refresh(appointment)

        logger.info(
            "appointment_created",
            appointment_id=str(appointment.id),
            patient_id=str(data.patient_id),
            office_id=str(office_id),
        )

        return appointment

    finally:
        # Step 8: Release lock
        await release_slot_lock(office_id, data.start_time, redis_client)


async def cancel_appointment(
    appointment_id: UUID,
    office_id: UUID,
    cancelled_by: str,
    reason: Optional[str],
    db: AsyncSession,
    redis_client: aioredis.Redis,
) -> Appointment:
    """
    Cancel an appointment.

    Args:
        appointment_id: Appointment ID
        office_id: Office ID
        cancelled_by: Who cancelled (patient|doctor)
        reason: Cancellation reason
        db: Database session
        redis_client: Redis client

    Returns:
        Updated Appointment object

    Raises:
        NotFoundError: If appointment not found
    """
    appointment = await db.get(Appointment, appointment_id)
    if not appointment or appointment.office_id != office_id:
        raise NotFoundError("Appointment not found")

    appointment.status = "cancelled"
    appointment.cancelled_by = cancelled_by
    appointment.cancellation_reason = reason

    # Invalidate cache
    await invalidate_availability_cache(
        office_id, appointment.start_time.date(), redis_client
    )

    await db.commit()
    await db.refresh(appointment)

    logger.info(
        "appointment_cancelled",
        appointment_id=str(appointment_id),
        office_id=str(office_id),
        cancelled_by=cancelled_by,
    )

    return appointment


async def reschedule_appointment(
    appointment_id: UUID,
    new_start_time: datetime,
    office_id: UUID,
    db: AsyncSession,
    redis_client: aioredis.Redis,
) -> Appointment:
    """
    Reschedule an appointment to a new time.

    Args:
        appointment_id: Appointment ID
        new_start_time: New appointment time
        office_id: Office ID
        db: Database session
        redis_client: Redis client

    Returns:
        Updated Appointment object

    Raises:
        NotFoundError: If appointment not found
        SlotNotAvailableError: If new slot is not available
    """
    appointment = await db.get(Appointment, appointment_id)
    if not appointment or appointment.office_id != office_id:
        raise NotFoundError("Appointment not found")

    # Acquire lock on new slot
    lock_acquired = await lock_slot_temporarily(
        office_id, new_start_time, redis_client
    )
    if not lock_acquired:
        raise SlotNotAvailableError("New slot is being booked by another user")

    try:
        # Invalidate old cache
        await invalidate_availability_cache(
            office_id, appointment.start_time.date(), redis_client
        )

        # Update appointment
        appointment.start_time = new_start_time
        appointment.end_time = new_start_time + timedelta(minutes=appointment.duration_min)

        # Reset reminder flags
        appointment.reminder_48h_sent = False
        appointment.reminder_24h_sent = False
        appointment.reminder_2h_sent = False
        appointment.confirmation_request_sent = False

        # Invalidate new cache
        await invalidate_availability_cache(
            office_id, new_start_time.date(), redis_client
        )

        await db.commit()
        await db.refresh(appointment)

        logger.info(
            "appointment_rescheduled",
            appointment_id=str(appointment_id),
            old_start_time=str(appointment.start_time),
            new_start_time=str(new_start_time),
        )

        return appointment

    finally:
        await release_slot_lock(office_id, new_start_time, redis_client)


async def confirm_appointment(
    appointment_id: UUID,
    office_id: UUID,
    db: AsyncSession,
) -> Appointment:
    """
    Confirm an appointment.

    Args:
        appointment_id: Appointment ID
        office_id: Office ID
        db: Database session

    Returns:
        Updated Appointment object

    Raises:
        NotFoundError: If appointment not found
    """
    appointment = await db.get(Appointment, appointment_id)
    if not appointment or appointment.office_id != office_id:
        raise NotFoundError("Appointment not found")

    appointment.status = "confirmed"

    # TODO: Send confirmation message to patient

    await db.commit()
    await db.refresh(appointment)

    logger.info(
        "appointment_confirmed",
        appointment_id=str(appointment_id),
        office_id=str(office_id),
    )

    return appointment


async def complete_appointment(
    appointment_id: UUID,
    office_id: UUID,
    notes: Optional[str],
    instructions: Optional[str],
    db: AsyncSession,
) -> Appointment:
    """
    Mark appointment as completed.

    Args:
        appointment_id: Appointment ID
        office_id: Office ID
        notes: Post-consultation notes
        instructions: Medical instructions
        db: Database session

    Returns:
        Updated Appointment object

    Raises:
        NotFoundError: If appointment not found
    """
    appointment = await db.get(Appointment, appointment_id)
    if not appointment or appointment.office_id != office_id:
        raise NotFoundError("Appointment not found")

    appointment.status = "completed"
    appointment.post_consultation_notes = notes
    appointment.medical_instructions = instructions

    # TODO: Schedule follow-up (post_follow_up task)

    await db.commit()
    await db.refresh(appointment)

    logger.info(
        "appointment_completed",
        appointment_id=str(appointment_id),
        office_id=str(office_id),
    )

    return appointment


async def get_appointments(
    office_id: UUID,
    start_date: Optional[datetime],
    end_date: Optional[datetime],
    status: Optional[str],
    db: AsyncSession,
) -> List[Appointment]:
    """
    Get appointments with filtering.

    Args:
        office_id: Office ID
        start_date: Filter by start date
        end_date: Filter by end date
        status: Filter by state
        db: Database session

    Returns:
        List of Appointment objects
    """
    query = select(Appointment).where(Appointment.office_id == office_id)

    if start_date:
        query = query.where(Appointment.start_time >= start_date)

    if end_date:
        query = query.where(Appointment.start_time <= end_date)

    if status:
        query = query.where(Appointment.status == status)

    result = await db.execute(query.order_by(Appointment.start_time))
    return result.scalars().all()


async def get_appointment(
    appointment_id: UUID,
    office_id: UUID,
    db: AsyncSession,
) -> Appointment:
    """
    Get a single appointment.

    Args:
        appointment_id: Appointment ID
        office_id: Office ID
        db: Database session

    Returns:
        Appointment object

    Raises:
        NotFoundError: If appointment not found
    """
    appointment = await db.get(Appointment, appointment_id)
    if not appointment or appointment.office_id != office_id:
        raise NotFoundError("Appointment not found")
    return appointment
