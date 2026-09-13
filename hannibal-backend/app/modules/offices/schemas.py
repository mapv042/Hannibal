"""Pydantic schemas for office CRUD operations."""

from __future__ import annotations

from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, Field

from app.core.constants import AssistantGender


class ServiceSchema(BaseModel):
    """One offered service and what it costs."""

    name: str = Field(..., description="Service name", max_length=200)
    price: Optional[str] = Field(
        None, description="Price as shown to the patient", max_length=100
    )


class IntakeQuestionsSchema(BaseModel):
    """What the office wants asked before the visit."""

    preset: List[str] = Field(
        default_factory=list, description="Ids from the intake catalogue"
    )
    custom: Optional[str] = Field(
        None, description="One extra question specific to this practice", max_length=500
    )


class CreateOfficeRequest(BaseModel):
    """Request to create a new office."""

    name: str = Field(..., description="Office name", max_length=255)
    doctor_first_name: Optional[str] = Field(
        None, description="Doctor's first name", max_length=100
    )
    doctor_last_name: Optional[str] = Field(
        None, description="Doctor's last name", max_length=100
    )
    specialty: Optional[str] = Field(
        None, description="Medical specialty", max_length=255
    )
    whatsapp_phone: Optional[str] = Field(
        None, description="WhatsApp phone number", max_length=20
    )
    owner_phone: Optional[str] = Field(
        None, description="Doctor's personal WhatsApp number", max_length=20
    )
    secondary_owner_phone: Optional[str] = Field(
        None,
        description="Optional second doctor-channel number (same permissions)",
        max_length=20,
    )
    city: Optional[str] = Field(None, description="City", max_length=100)
    state: Optional[str] = Field(None, description="State", max_length=100)
    address: Optional[str] = Field(None, description="Address", max_length=500)


class UpdateOfficeRequest(BaseModel):
    """Request to update an office."""

    name: Optional[str] = Field(None, description="Office name", max_length=255)
    doctor_first_name: Optional[str] = Field(
        None, description="Doctor's first name", max_length=100
    )
    doctor_last_name: Optional[str] = Field(
        None, description="Doctor's last name", max_length=100
    )
    specialty: Optional[str] = Field(
        None, description="Medical specialty", max_length=255
    )
    whatsapp_phone: Optional[str] = Field(
        None, description="WhatsApp phone number", max_length=20
    )
    owner_phone: Optional[str] = Field(
        None, description="Doctor's personal WhatsApp number", max_length=20
    )
    secondary_owner_phone: Optional[str] = Field(
        None,
        description="Optional second doctor-channel number (same permissions)",
        max_length=20,
    )
    city: Optional[str] = Field(None, description="City", max_length=100)
    state: Optional[str] = Field(None, description="State", max_length=100)
    address: Optional[str] = Field(None, description="Address", max_length=500)
    assistant_tone: Optional[str] = Field(
        None, description="Assistant tone (formal|informal)"
    )
    assistant_name: Optional[str] = Field(None, description="Assistant name")
    assistant_gender: Optional[str] = Field(
        None, description="Assistant grammatical gender (femenino|masculino|neutro)"
    )
    services: Optional[List[ServiceSchema]] = Field(
        None, description="Service catalogue with prices"
    )
    accepts_insurance: Optional[str] = Field(
        None, description="Whether the office takes insurance (si|algunos|no)"
    )
    insurances: Optional[List[str]] = Field(
        None, description="Canonical insurer ids the office accepts"
    )
    emergency_symptoms: Optional[List[str]] = Field(
        None, description="Alarm symptoms that must be escalated to the doctor"
    )
    intake_questions: Optional[IntakeQuestionsSchema] = Field(
        None, description="What the assistant asks the patient before the visit"
    )
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
    notify_new_appointment: Optional[bool] = Field(
        None, description="Notify the doctor when the bot books a new appointment"
    )
    notify_cancellation: Optional[bool] = Field(
        None, description="Notify the doctor when a patient cancels an appointment"
    )
    notify_new_patient: Optional[bool] = Field(
        None, description="Notify the doctor when a new patient registers"
    )
    notify_unconfirmed: Optional[bool] = Field(
        None, description="Notify the doctor of today's unconfirmed appointments"
    )
    notify_arrival: Optional[bool] = Field(
        None, description="Notify the doctor when a patient reports arriving"
    )


class ReminderRuleSchema(BaseModel):
    """A single per-office reminder rule."""

    reminder_type: str = Field(
        ...,
        description=(
            "Reminder kind: week_before | day_before | 6h | at_time | post_appointment"
        ),
    )
    offset_minutes: int = Field(
        ...,
        description="Signed offset from appointment start in minutes "
        "(negative = before, positive = after)",
    )
    enabled: bool = Field(True, description="Whether this reminder is active")

    class Config:
        from_attributes = True


class UpdateReminderRulesRequest(BaseModel):
    """Replace the full set of reminder rules for an office."""

    rules: list[ReminderRuleSchema] = Field(
        ..., description="Complete list of reminder rules for the office"
    )


class OfficeResponse(BaseModel):
    """Response model for office data."""

    id: UUID
    user_id: UUID
    name: str
    doctor_first_name: Optional[str]
    doctor_last_name: Optional[str]
    specialty: Optional[str]
    whatsapp_phone: Optional[str]
    owner_phone: Optional[str]
    secondary_owner_phone: Optional[str]
    city: Optional[str]
    state: Optional[str]
    address: Optional[str]
    assistant_tone: str
    assistant_name: str
    assistant_gender: str
    custom_prompt: Optional[str]
    welcome_message: Optional[str]
    new_patient_duration_min: int
    returning_patient_duration_min: int
    new_patient_cost: Optional[str]
    returning_patient_cost: Optional[str]
    # Structured onboarding data — returned so the wizard can re-hydrate; before
    # these existed the doctor lost everything on re-entry.
    services: Optional[List[ServiceSchema]]
    accepts_insurance: Optional[str]
    insurances: Optional[List[str]]
    emergency_symptoms: Optional[List[str]]
    intake_questions: Optional[IntakeQuestionsSchema]
    is_active: bool
    onboarding_completed: bool
    notify_new_appointment: bool
    notify_cancellation: bool
    notify_new_patient: bool
    notify_unconfirmed: bool
    notify_arrival: bool
    plan: str

    class Config:
        from_attributes = True
