"""Pydantic schemas for patient CRUD operations."""

from __future__ import annotations

from datetime import datetime, date
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


class CreatePatientRequest(BaseModel):
    """Request to create a new patient."""

    name: Optional[str] = Field(None, description="Patient name", max_length=255)
    phone: str = Field(..., description="Phone number", max_length=20)
    whatsapp_id: str = Field(..., description="WhatsApp Business API ID", max_length=50)
    email: Optional[str] = Field(None, description="Email address", max_length=255)
    birth_date: Optional[date] = Field(None, description="Birth date")
    main_reason: Optional[str] = Field(
        None, description="Main reason for visit", max_length=500
    )
    how_found_us: Optional[str] = Field(
        None, description="How they found us", max_length=255
    )
    internal_notes: Optional[str] = Field(
        None, description="Internal notes", max_length=2000
    )


class UpdatePatientRequest(BaseModel):
    """Request to update a patient."""

    name: Optional[str] = Field(None, description="Patient name", max_length=255)
    email: Optional[str] = Field(None, description="Email address", max_length=255)
    birth_date: Optional[date] = Field(None, description="Birth date")
    main_reason: Optional[str] = Field(
        None, description="Main reason for visit", max_length=500
    )
    how_found_us: Optional[str] = Field(
        None, description="How they found us", max_length=255
    )
    internal_notes: Optional[str] = Field(
        None, description="Internal notes", max_length=2000
    )
    is_active: Optional[bool] = Field(None, description="Is active")


class PatientResponse(BaseModel):
    """Response model for patient data."""

    id: UUID
    office_id: UUID
    name: Optional[str]
    phone: str
    whatsapp_id: str
    email: Optional[str]
    # The API keeps its original names; the columns are named differently.
    # Without the aliases every row failed validation ("Field required") and
    # GET /api/patients answered 500 as soon as the office had one patient.
    birth_date: Optional[date] = Field(None, validation_alias="date_of_birth")
    main_reason: Optional[str] = Field(None, validation_alias="primary_reason")
    how_found_us: Optional[str] = Field(None, validation_alias="how_they_found_us")
    internal_notes: Optional[str]
    is_active: bool
    first_appointment_at: Optional[datetime]
    last_appointment_at: Optional[datetime]
    total_appointments: int
    created_at: datetime

    class Config:
        from_attributes = True
