"""Service layer for appointment operations."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import List, Optional
from uuid import UUID

import redis.asyncio as aioredis
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Appointment, Office, Patient
from app.modules.reminders.scheduler import schedule_reminders_for_appointment
from app.modules.scheduling.schemas import CreateAppointmentRequest, UpdateAppointmentRequest
from app.modules.scheduling.availability import (
    check_slot_bookable,
    invalidate_availability_cache,
    lock_slot_temporarily,
    release_slot_lock,
)
from app.modules.scheduling.booking import book_appointment
from app.core.exceptions import NotFoundError, SlotNotAvailableError
from app.utils.logger import get_logger
from app.utils.phone import display_or_raw

logger = get_logger(__name__)


async def create_appointment(
    data: CreateAppointmentRequest,
    office_id: UUID,
    db: AsyncSession,
    redis_client: aioredis.Redis,
) -> Appointment:
    """
    Create a new appointment from the dashboard.

    Delegates to the shared booking engine (validation, slot lock, Google
    Calendar event, cache invalidation, reminders) and maps failures to the
    HTTP exception contract.

    Raises:
        NotFoundError: If patient or office not found
        SlotNotAvailableError: If slot is not available
    """
    # Validate patient exists
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

    office = await db.get(Office, office_id)
    if not office:
        raise NotFoundError("Office not found")

    phone_line = f"Teléfono: {display_or_raw(patient.phone)}\n" if patient.phone else ""
    outcome = await book_appointment(
        db,
        office,
        patient_id=data.patient_id,
        start_dt=data.start_time,
        duration_min=data.duration_min,
        reason=data.consultation_reason,
        appt_type=data.appointment_type,
        gcal_title=f"Cita: {patient.name or 'Paciente'}",
        gcal_description=(
            f"Motivo: {data.consultation_reason}\n{phone_line}Agendada desde el dashboard"
        ),
        redis_client=redis_client,
    )
    if outcome.error:
        raise SlotNotAvailableError(outcome.error)

    appointment = outcome.appointment
    await db.commit()
    await db.refresh(appointment)

    logger.info(
        "appointment_created",
        appointment_id=str(appointment.id),
        patient_id=str(data.patient_id),
        office_id=str(office_id),
    )

    return appointment


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
        office_id, appointment.start_datetime.date(), redis_client
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
        # Re-validate the new slot under the lock before moving the appointment
        new_end_time = new_start_time + timedelta(minutes=appointment.duration_minutes)
        conflict = await check_slot_bookable(
            office_id, new_start_time, new_end_time, db
        )
        if conflict:
            raise SlotNotAvailableError(conflict)

        # Invalidate old cache
        await invalidate_availability_cache(
            office_id, appointment.start_datetime.date(), redis_client
        )

        # Update appointment
        appointment.start_datetime = new_start_time
        appointment.end_datetime = new_start_time + timedelta(minutes=appointment.duration_minutes)

        # Reset reminder flags (new datetime ⇒ reminders must be rescheduled)
        appointment.reminder_day_before_sent = False
        appointment.reminder_4h_sent = False
        appointment.reminder_1h_sent = False
        appointment.follow_up_sent = False
        appointment.confirmation_request_sent = False

        # Invalidate new cache
        await invalidate_availability_cache(
            office_id, new_start_time.date(), redis_client
        )

        await db.commit()
        await db.refresh(appointment)

        # Reminders were reset above — schedule them for the new datetime
        await schedule_reminders_for_appointment(
            db, office_id, appointment.id, appointment.start_datetime
        )

        logger.info(
            "appointment_rescheduled",
            appointment_id=str(appointment_id),
            old_start_time=str(appointment.start_datetime),
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
    appointment.instructions = instructions

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
        query = query.where(Appointment.start_datetime >= start_date)

    if end_date:
        query = query.where(Appointment.start_datetime <= end_date)

    if status:
        query = query.where(Appointment.status == status)

    result = await db.execute(query.order_by(Appointment.start_datetime))
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
