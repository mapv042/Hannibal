"""Pydantic schemas for appointment scheduling module."""

from __future__ import annotations

from datetime import datetime, date
from typing import Optional, List
from uuid import UUID

from pydantic import BaseModel, Field


class AvailableSlot(BaseModel):
    """Available appointment slot."""

    start_time: datetime = Field(..., description="Start time of slot")
    end_time: datetime = Field(..., description="End time of slot")

    class Config:
        from_attributes = True


class CreateAppointmentRequest(BaseModel):
    """Request to create a new appointment."""

    patient_id: UUID = Field(..., description="Patient ID")
    start_time: datetime = Field(..., description="Appointment start time")
    duration_min: int = Field(30, description="Duration in minutes", ge=15)
    appointment_type: str = Field("first_visit", description="Appointment type")
    consultation_reason: Optional[str] = Field(
        None, description="Reason for consultation", max_length=500
    )


class UpdateAppointmentRequest(BaseModel):
    """Request to update an existing appointment."""

    status: Optional[str] = Field(
        None, description="New appointment state"
    )  # scheduled|confirmed|completed|no_show|cancelled
    post_consultation_notes: Optional[str] = Field(
        None, description="Post-consultation notes", max_length=2000
    )
    instructions: Optional[str] = Field(
        None, description="Medical instructions", max_length=2000
    )
    cancelled_by: Optional[str] = Field(
        None, description="Who cancelled (patient|doctor)"
    )
    cancellation_reason: Optional[str] = Field(
        None, description="Cancellation reason", max_length=500
    )


class AppointmentResponse(BaseModel):
    """Full appointment data response."""

    id: UUID
    office_id: UUID
    patient_id: UUID
    start_datetime: datetime
    end_datetime: datetime
    duration_minutes: int
    type: str
    consultation_reason: Optional[str]
    status: str
    post_consultation_notes: Optional[str]
    instructions: Optional[str]
    cancelled_by: Optional[str]
    cancellation_reason: Optional[str]
    reminder_morning_sent: bool
    reminder_4h_sent: bool
    reminder_1h_sent: bool
    reminder_15m_sent: bool
    follow_up_sent: bool
    google_event_id: Optional[str]
    created_at: datetime
    updated_at: Optional[datetime]

    class Config:
        from_attributes = True


class AvailabilityRequest(BaseModel):
    """Request for availability slots."""

    target_date: date = Field(..., description="Date to check availability")
    duration_min: int = Field(30, description="Desired appointment duration", ge=15)


class AvailabilityResponse(BaseModel):
    """Response with available slots."""

    slots: List[AvailableSlot] = Field(..., description="List of available slots")


class RescheduleAppointmentRequest(BaseModel):
    """Request to reschedule an appointment."""

    new_start_time: datetime = Field(..., description="New appointment time")


class ConfirmAppointmentRequest(BaseModel):
    """Request to confirm an appointment."""

    pass


class CompleteAppointmentRequest(BaseModel):
    """Request to mark appointment as completed."""

    post_consultation_notes: Optional[str] = Field(
        None, description="Post-consultation notes", max_length=2000
    )
    instructions: Optional[str] = Field(
        None, description="Medical instructions", max_length=2000
    )


class CancelAppointmentRequest(BaseModel):
    """Request to cancel an appointment."""

    cancelled_by: str = Field(..., description="Who is cancelling (patient|doctor)")
    cancellation_reason: Optional[str] = Field(
        None, description="Cancellation reason", max_length=500
    )


# ── Availability Schedule schemas ──────────────────────────────────────────


class AvailabilityScheduleItem(BaseModel):
    """Single availability schedule entry."""

    day_of_week: int = Field(..., description="0=Sun, 1=Mon, ..., 6=Sat", ge=0, le=6)
    start_time: str = Field(..., description="Start time in HH:MM format")
    end_time: str = Field(..., description="End time in HH:MM format")
    appointment_duration_min: int = Field(30, description="Appointment duration in minutes", ge=10)
    buffer_minutes: int = Field(10, description="Buffer between appointments", ge=0)


class BulkUpsertSchedulesRequest(BaseModel):
    """Request to bulk upsert availability schedules for an office."""

    schedules: List[AvailabilityScheduleItem]


class AvailabilityScheduleResponse(BaseModel):
    """Response model for a single availability schedule."""

    id: UUID
    office_id: UUID
    day_of_week: int
    start_time: str
    end_time: str
    appointment_duration_min: int
    buffer_minutes: int
    is_active: bool

    class Config:
        from_attributes = True
