"""FastAPI router for patient endpoints."""

from __future__ import annotations

from uuid import UUID
from typing import List

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db, get_current_user
from app.db.models import Office
from app.modules.patients.schemas import (
    CreatePatientRequest,
    UpdatePatientRequest,
    PatientResponse,
)
from app.modules.patients.service import (
    create_patient,
    get_patient,
    list_patients,
    update_patient,
    delete_patient,
    find_patient_by_whatsapp_id,
)
from app.utils.logger import get_logger
from sqlalchemy import select
from app.core.exceptions import NotFoundError

logger = get_logger(__name__)

router = APIRouter(tags=["Patients"])


async def get_office_from_user(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Office:
    """Get office for authenticated user."""
    user_id = current_user.get("sub")
    result = await db.execute(
        select(Office).where(Office.user_id == UUID(user_id))
    )
    office = result.scalar_one_or_none()

    if not office:
        raise NotFoundError("Office not found")

    return office


@router.post("", response_model=PatientResponse, status_code=201)
async def create_patient_endpoint(
    request: CreatePatientRequest,
    db: AsyncSession = Depends(get_db),
    office: Office = Depends(get_office_from_user),
):
    """
    Create a new patient.

    Request Body:
        name: Patient name (optional)
        phone: Phone number (required)
        whatsapp_id: WhatsApp Business API ID (required)
        email: Email address (optional)
        birth_date: Birth date (optional)
        main_reason: Main reason for visit (optional)
        how_found_us: How they found us (optional)
        internal_notes: Internal notes (optional)

    Returns:
        Created patient
    """
    logger.info(
        "create_patient",
        office_id=str(office.id),
        phone=request.phone,
    )

    patient = await create_patient(
        data=request,
        office_id=office.id,
        db=db,
    )

    return patient


@router.get("", response_model=List[PatientResponse])
async def list_patients_endpoint(
    active_only: bool = Query(True, description="Only return active patients"),
    db: AsyncSession = Depends(get_db),
    office: Office = Depends(get_office_from_user),
):
    """
    List all patients for the office.

    Query Parameters:
        active_only: Only return active patients (default true)

    Returns:
        List of patients
    """
    logger.info(
        "list_patients",
        office_id=str(office.id),
    )

    patients = await list_patients(
        office_id=office.id,
        active_only=active_only,
        db=db,
    )

    return patients


@router.get("/{patient_id}", response_model=PatientResponse)
async def get_patient_endpoint(
    patient_id: UUID,
    db: AsyncSession = Depends(get_db),
    office: Office = Depends(get_office_from_user),
):
    """Get a specific patient."""
    logger.info(
        "get_patient",
        patient_id=str(patient_id),
        office_id=str(office.id),
    )

    patient = await get_patient(
        patient_id=patient_id,
        office_id=office.id,
        db=db,
    )

    return patient


@router.put("/{patient_id}", response_model=PatientResponse)
async def update_patient_endpoint(
    patient_id: UUID,
    request: UpdatePatientRequest,
    db: AsyncSession = Depends(get_db),
    office: Office = Depends(get_office_from_user),
):
    """Update a patient."""
    logger.info(
        "update_patient",
        patient_id=str(patient_id),
        office_id=str(office.id),
    )

    patient = await update_patient(
        patient_id=patient_id,
        office_id=office.id,
        data=request,
        db=db,
    )

    return patient


@router.delete("/{patient_id}", status_code=204)
async def delete_patient_endpoint(
    patient_id: UUID,
    db: AsyncSession = Depends(get_db),
    office: Office = Depends(get_office_from_user),
):
    """Delete a patient."""
    logger.info(
        "delete_patient",
        patient_id=str(patient_id),
        office_id=str(office.id),
    )

    await delete_patient(
        patient_id=patient_id,
        office_id=office.id,
        db=db,
    )


@router.get("/whatsapp/{whatsapp_id}", response_model=PatientResponse)
async def get_patient_by_whatsapp(
    whatsapp_id: str,
    db: AsyncSession = Depends(get_db),
    office: Office = Depends(get_office_from_user),
):
    """Get patient by WhatsApp ID."""
    logger.info(
        "get_patient_by_whatsapp",
        whatsapp_id=whatsapp_id,
        office_id=str(office.id),
    )

    patient = await find_patient_by_whatsapp_id(
        whatsapp_id=whatsapp_id,
        office_id=office.id,
        db=db,
    )

    if not patient:
        raise NotFoundError("Patient not found")

    return patient
