"""Service layer for patient CRUD operations."""

from __future__ import annotations

from uuid import UUID
from typing import List, Optional

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Patient, Office
from app.modules.patients.schemas import (
    CreatePatientRequest,
    UpdatePatientRequest,
)
from app.core.exceptions import NotFoundError
from app.utils.logger import get_logger

logger = get_logger(__name__)


async def create_patient(
    data: CreatePatientRequest,
    office_id: UUID,
    db: AsyncSession,
) -> Patient:
    """
    Create a new patient.

    Args:
        data: Patient creation data
        office_id: Office ID
        db: Database session

    Returns:
        Created Patient object
    """
    patient = Patient(
        office_id=office_id,
        name=data.name,
        phone=data.phone,
        whatsapp_id=data.whatsapp_id,
        email=data.email,
        birth_date=data.birth_date,
        main_reason=data.main_reason,
        how_found_us=data.how_found_us,
        internal_notes=data.internal_notes,
    )

    db.add(patient)
    await db.commit()
    await db.refresh(patient)

    logger.info(
        "patient_created",
        patient_id=str(patient.id),
        office_id=str(office_id),
        name=data.name,
    )

    return patient


async def get_patient(
    patient_id: UUID,
    office_id: UUID,
    db: AsyncSession,
) -> Patient:
    """
    Get a single patient.

    Args:
        patient_id: Patient ID
        office_id: Office ID (for authorization)
        db: Database session

    Returns:
        Patient object

    Raises:
        NotFoundError: If patient not found
    """
    patient = await db.get(Patient, patient_id)

    if not patient or patient.office_id != office_id:
        raise NotFoundError("Patient not found")

    return patient


async def list_patients(
    office_id: UUID,
    active_only: bool = True,
    db: AsyncSession = None,
) -> List[Patient]:
    """
    List all patients for an office.

    Args:
        office_id: Office ID
        active_only: Only return active patients
        db: Database session

    Returns:
        List of Patient objects
    """
    query = select(Patient).where(Patient.office_id == office_id)

    if active_only:
        query = query.where(Patient.is_active == True)

    result = await db.execute(query.order_by(Patient.created_at.desc()))
    return result.scalars().all()


async def update_patient(
    patient_id: UUID,
    office_id: UUID,
    data: UpdatePatientRequest,
    db: AsyncSession,
) -> Patient:
    """
    Update a patient.

    Args:
        patient_id: Patient ID
        office_id: Office ID (for authorization)
        data: Update data
        db: Database session

    Returns:
        Updated Patient object

    Raises:
        NotFoundError: If patient not found
    """
    patient = await get_patient(patient_id, office_id, db)

    # Update fields
    if data.name is not None:
        patient.name = data.name
    if data.email is not None:
        patient.email = data.email
    if data.birth_date is not None:
        patient.birth_date = data.birth_date
    if data.main_reason is not None:
        patient.main_reason = data.main_reason
    if data.how_found_us is not None:
        patient.how_found_us = data.how_found_us
    if data.internal_notes is not None:
        patient.internal_notes = data.internal_notes
    if data.is_active is not None:
        patient.is_active = data.is_active

    await db.commit()
    await db.refresh(patient)

    logger.info(
        "patient_updated",
        patient_id=str(patient_id),
        office_id=str(office_id),
    )

    return patient


async def delete_patient(
    patient_id: UUID,
    office_id: UUID,
    db: AsyncSession,
) -> None:
    """
    Delete a patient.

    Args:
        patient_id: Patient ID
        office_id: Office ID (for authorization)
        db: Database session

    Raises:
        NotFoundError: If patient not found
    """
    patient = await get_patient(patient_id, office_id, db)

    await db.delete(patient)
    await db.commit()

    logger.info(
        "patient_deleted",
        patient_id=str(patient_id),
        office_id=str(office_id),
    )


async def find_patient_by_whatsapp_id(
    whatsapp_id: str,
    office_id: UUID,
    db: AsyncSession,
) -> Optional[Patient]:
    """
    Find a patient by WhatsApp ID.

    Args:
        whatsapp_id: WhatsApp Business API ID
        office_id: Office ID
        db: Database session

    Returns:
        Patient object or None if not found
    """
    result = await db.execute(
        select(Patient).where(
            and_(
                Patient.whatsapp_id == whatsapp_id,
                Patient.office_id == office_id,
            )
        )
    )
    return result.scalar_one_or_none()
