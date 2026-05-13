"""FastAPI router for appointment scheduling endpoints."""

from __future__ import annotations

from datetime import datetime, date
from typing import List, Optional
from uuid import UUID

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db, get_current_user, get_redis
from app.core.exceptions import NotFoundError
from app.db.models import Office, Waitlist
from app.modules.scheduling.schemas import (
    AvailabilityRequest,
    AvailabilityResponse,
    CreateAppointmentRequest,
    AppointmentResponse,
    UpdateAppointmentRequest,
    RescheduleAppointmentRequest,
    CancelAppointmentRequest,
    CompleteAppointmentRequest,
    BulkUpsertSchedulesRequest,
    AvailabilityScheduleResponse,
)
from app.modules.scheduling.availability import (
    get_available_slots,
    get_upcoming_slots,
)
from app.modules.scheduling.appointments_service import (
    create_appointment,
    cancel_appointment,
    reschedule_appointment,
    confirm_appointment,
    complete_appointment,
    get_appointment,
    get_appointments,
)
from app.modules.scheduling.blocks_service import get_blocks
from app.utils.logger import get_logger
from sqlalchemy import select

logger = get_logger(__name__)

router = APIRouter(tags=["Scheduling"])


async def get_office_from_user(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Office:
    """Get office for authenticated user."""
    from sqlalchemy import select

    user_id = current_user.get("sub")
    result = await db.execute(
        select(Office).where(Office.user_id == user_id)
    )
    office = result.scalar_one_or_none()

    if not office:
        raise NotFoundError("Office not found")

    return office


@router.get("/availability", response_model=AvailabilityResponse)
async def get_availability(
    date: date = Query(..., description="Date to check availability"),
    duration_min: int = Query(30, ge=15, description="Requested duration in minutes"),
    db: AsyncSession = Depends(get_db),
    redis_client: aioredis.Redis = Depends(get_redis),
    office: Office = Depends(get_office_from_user),
):
    """
    Get available appointment slots for a given date.

    Query Parameters:
        date: Date to check (YYYY-MM-DD)
        duration_min: Desired duration in minutes (default 30)

    Returns:
        List of available slots
    """
    logger.info(
        "get_availability",
        office_id=str(office.id),
        date=str(date),
        duration=duration_min,
    )

    slots = await get_available_slots(
        office_id=office.id,
        date_=date,
        duration_min=duration_min,
        db=db,
        redis_client=redis_client,
    )

    return AvailabilityResponse(slots=slots)


@router.get("/upcoming-slots")
async def get_upcoming_slots_endpoint(
    days: int = Query(7, ge=1, le=60, description="Number of days to check"),
    db: AsyncSession = Depends(get_db),
    redis_client: aioredis.Redis = Depends(get_redis),
    office: Office = Depends(get_office_from_user),
):
    """
    Get all available slots for the next N days.

    Query Parameters:
        days: Number of days to check (1-60, default 7)

    Returns:
        List of available slots sorted by date
    """
    logger.info(
        "get_upcoming_slots",
        office_id=str(office.id),
        days=days,
    )

    slots = await get_upcoming_slots(
        office_id=office.id,
        days=days,
        db=db,
        redis_client=redis_client,
    )

    return {"slots": slots}


@router.get("/appointments", response_model=List[AppointmentResponse])
async def list_appointments(
    start_date: Optional[datetime] = Query(None, description="Filter start date"),
    end_date: Optional[datetime] = Query(None, description="Filter end date"),
    status: Optional[str] = Query(
        None,
        description="Filter by state (scheduled|confirmed|completed|no_show|cancelled)",
    ),
    db: AsyncSession = Depends(get_db),
    office: Office = Depends(get_office_from_user),
):
    """
    List appointments with optional filtering.

    Query Parameters:
        start_date: Filter from date
        end_date: Filter to date
        status: Filter by appointment state

    Returns:
        List of appointments
    """
    logger.info(
        "list_appointments",
        office_id=str(office.id),
        start_date=start_date,
        end_date=end_date,
        status=status,
    )

    appointments = await get_appointments(
        office_id=office.id,
        start_date=start_date,
        end_date=end_date,
        status=status,
        db=db,
    )

    return appointments


@router.get("/appointments/{appointment_id}", response_model=AppointmentResponse)
async def get_appointment_endpoint(
    appointment_id: UUID,
    db: AsyncSession = Depends(get_db),
    office: Office = Depends(get_office_from_user),
):
    """Get a single appointment."""
    logger.info("get_appointment", appointment_id=str(appointment_id), office_id=str(office.id))

    appointment = await get_appointment(
        appointment_id=appointment_id,
        office_id=office.id,
        db=db,
    )

    return appointment


@router.post("/appointments", response_model=AppointmentResponse, status_code=201)
async def create_new_appointment(
    request: CreateAppointmentRequest,
    db: AsyncSession = Depends(get_db),
    redis_client: aioredis.Redis = Depends(get_redis),
    office: Office = Depends(get_office_from_user),
):
    """
    Create a new appointment.

    Request Body:
        patient_id: Patient ID (UUID)
        start_time: Appointment start time (ISO 8601)
        duration_min: Duration in minutes
        appointment_type: Appointment type (first_visit|follow_up)
        consultation_reason: Reason for consultation

    Returns:
        Created appointment
    """
    logger.info(
        "create_appointment",
        office_id=str(office.id),
        patient_id=str(request.patient_id),
    )

    appointment = await create_appointment(
        data=request,
        office_id=office.id,
        db=db,
        redis_client=redis_client,
    )

    return appointment


@router.put("/appointments/{appointment_id}/confirm", response_model=AppointmentResponse)
async def confirm_appointment_endpoint(
    appointment_id: UUID,
    db: AsyncSession = Depends(get_db),
    office: Office = Depends(get_office_from_user),
):
    """Confirm an appointment."""
    logger.info(
        "confirm_appointment",
        appointment_id=str(appointment_id),
        office_id=str(office.id),
    )

    appointment = await confirm_appointment(
        appointment_id=appointment_id,
        office_id=office.id,
        db=db,
    )

    return appointment


@router.put("/appointments/{appointment_id}/complete", response_model=AppointmentResponse)
async def complete_appointment_endpoint(
    appointment_id: UUID,
    request: CompleteAppointmentRequest,
    db: AsyncSession = Depends(get_db),
    office: Office = Depends(get_office_from_user),
):
    """Mark appointment as completed."""
    logger.info(
        "complete_appointment",
        appointment_id=str(appointment_id),
        office_id=str(office.id),
    )

    appointment = await complete_appointment(
        appointment_id=appointment_id,
        office_id=office.id,
        notes=request.post_consultation_notes,
        instructions=request.instructions,
        db=db,
    )

    return appointment


@router.put("/appointments/{appointment_id}/reschedule", response_model=AppointmentResponse)
async def reschedule_appointment_endpoint(
    appointment_id: UUID,
    request: RescheduleAppointmentRequest,
    db: AsyncSession = Depends(get_db),
    redis_client: aioredis.Redis = Depends(get_redis),
    office: Office = Depends(get_office_from_user),
):
    """Reschedule an appointment."""
    logger.info(
        "reschedule_appointment",
        appointment_id=str(appointment_id),
        office_id=str(office.id),
    )

    appointment = await reschedule_appointment(
        appointment_id=appointment_id,
        new_start_time=request.new_start_time,
        office_id=office.id,
        db=db,
        redis_client=redis_client,
    )

    return appointment


@router.delete("/appointments/{appointment_id}", status_code=204)
async def cancel_appointment_endpoint(
    appointment_id: UUID,
    request: CancelAppointmentRequest,
    db: AsyncSession = Depends(get_db),
    redis_client: aioredis.Redis = Depends(get_redis),
    office: Office = Depends(get_office_from_user),
):
    """Cancel an appointment."""
    logger.info(
        "cancel_appointment",
        appointment_id=str(appointment_id),
        office_id=str(office.id),
    )

    await cancel_appointment(
        appointment_id=appointment_id,
        office_id=office.id,
        cancelled_by=request.cancelled_by,
        reason=request.cancellation_reason,
        db=db,
        redis_client=redis_client,
    )


@router.get("/waitlist")
async def get_waitlist(
    db: AsyncSession = Depends(get_db),
    office: Office = Depends(get_office_from_user),
):
    """
    Get waiting list entries.

    Returns:
        List of waiting list entries
    """
    logger.info(
        "get_waitlist",
        office_id=str(office.id),
    )

    result = await db.execute(
        select(Waitlist).where(
            Waitlist.office_id == office.id,
        )
    )
    entries = result.scalars().all()

    return {"entries": entries}


# ── Availability Schedule CRUD ─────────────────────────────────────────────


@router.get("/schedules", response_model=List[AvailabilityScheduleResponse])
async def get_schedules_endpoint(
    db: AsyncSession = Depends(get_db),
    office: Office = Depends(get_office_from_user),
):
    """Get all availability schedules for the current user's office."""
    from app.modules.scheduling.availability_crud import get_schedules

    schedules = await get_schedules(
        office_id=office.id,
        user_id=office.user_id,
        db=db,
    )

    # Convert time objects to HH:MM strings
    results = []
    for s in schedules:
        results.append(AvailabilityScheduleResponse(
            id=s.id,
            office_id=s.office_id,
            day_of_week=s.day_of_week,
            start_time=s.start_time.strftime("%H:%M"),
            end_time=s.end_time.strftime("%H:%M"),
            appointment_duration_min=s.appointment_duration_min,
            buffer_minutes=s.buffer_minutes,
            is_active=s.is_active,
        ))

    return results


@router.put("/schedules", response_model=List[AvailabilityScheduleResponse])
async def upsert_schedules_endpoint(
    request: BulkUpsertSchedulesRequest,
    db: AsyncSession = Depends(get_db),
    office: Office = Depends(get_office_from_user),
):
    """Bulk upsert availability schedules — replaces all existing schedules."""
    from app.modules.scheduling.availability_crud import bulk_upsert_schedules

    schedules = await bulk_upsert_schedules(
        office_id=office.id,
        user_id=office.user_id,
        schedules_data=request.schedules,
        db=db,
    )

    results = []
    for s in schedules:
        results.append(AvailabilityScheduleResponse(
            id=s.id,
            office_id=s.office_id,
            day_of_week=s.day_of_week,
            start_time=s.start_time.strftime("%H:%M"),
            end_time=s.end_time.strftime("%H:%M"),
            appointment_duration_min=s.appointment_duration_min,
            buffer_minutes=s.buffer_minutes,
            is_active=s.is_active,
        ))

    return results
