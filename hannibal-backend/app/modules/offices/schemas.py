"""Pydantic schemas for office CRUD operations."""

from __future__ import annotations

from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


class CreateOfficeRequest(BaseModel):
    """Request to create a new office."""

    name: str = Field(..., description="Office name", max_length=255)
    specialty: Optional[str] = Field(
        None, description="Medical specialty", max_length=255
    )
    whatsapp_phone: Optional[str] = Field(
        None, description="WhatsApp phone number", max_length=20
    )
    owner_phone: Optional[str] = Field(
        None, description="Doctor's personal WhatsApp number", max_length=20
    )
    city: Optional[str] = Field(None, description="City", max_length=100)
    state: Optional[str] = Field(None, description="State", max_length=100)
    address: Optional[str] = Field(None, description="Address", max_length=500)


class UpdateOfficeRequest(BaseModel):
    """Request to update an office."""

    name: Optional[str] = Field(None, description="Office name", max_length=255)
    specialty: Optional[str] = Field(
        None, description="Medical specialty", max_length=255
    )
    whatsapp_phone: Optional[str] = Field(
        None, description="WhatsApp phone number", max_length=20
    )
    owner_phone: Optional[str] = Field(
        None, description="Doctor's personal WhatsApp number", max_length=20
    )
    city: Optional[str] = Field(None, description="City", max_length=100)
    state: Optional[str] = Field(None, description="State", max_length=100)
    address: Optional[str] = Field(None, description="Address", max_length=500)
    assistant_tone: Optional[str] = Field(
        None, description="Assistant tone (formal|informal)"
    )
    assistant_name: Optional[str] = Field(None, description="Assistant name")
    custom_prompt: Optional[str] = Field(
        None, description="Custom AI prompt instructions", max_length=5000
    )
    welcome_message: Optional[str] = Field(
        None, description="Welcome message for first-time patients", max_length=2000
    )
    new_patient_duration_min: Optional[int] = Field(
        None, description="Appointment duration for new patients (minutes)", ge=10, le=120
    )
    returning_patient_duration_min: Optional[int] = Field(
        None, description="Appointment duration for returning patients (minutes)", ge=10, le=120
    )
    new_patient_cost: Optional[str] = Field(
        None, description="Consultation cost for new patients", max_length=100
    )
    returning_patient_cost: Optional[str] = Field(
        None, description="Consultation cost for returning patients", max_length=100
    )
    is_active: Optional[bool] = Field(None, description="Is active")
    onboarding_completed: Optional[bool] = Field(
        None, description="Whether onboarding has been completed"
    )


class OfficeResponse(BaseModel):
    """Response model for office data."""

    id: UUID
    user_id: UUID
    name: str
    specialty: Optional[str]
    whatsapp_phone: Optional[str]
    owner_phone: Optional[str]
    city: Optional[str]
    state: Optional[str]
    address: Optional[str]
    assistant_tone: str
    assistant_name: str
    custom_prompt: Optional[str]
    welcome_message: Optional[str]
    new_patient_duration_min: int
    returning_patient_duration_min: int
    new_patient_cost: Optional[str]
    returning_patient_cost: Optional[str]
    is_active: bool
    onboarding_completed: bool
    plan: str

    class Config:
        from_attributes = True
