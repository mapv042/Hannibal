"""
SQLAlchemy ORM models for WhatsApp appointment management SaaS.

Multi-tenant architecture with support for:
- Multiple offices (clinics/practices) per user
- WhatsApp integration with Twilio/Meta Business API
- Google Calendar synchronization
- Automated appointment scheduling and reminders
- Patient conversation tracking
"""

from __future__ import annotations

import uuid
from datetime import datetime, date, time
from typing import Optional, List

from sqlalchemy import (
    Boolean,
    DateTime,
    Date,
    String,
    Integer,
    Time,
    ForeignKey,
    func,
    Index,
)
from sqlalchemy.dialects.postgresql import UUID, ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Office(Base):
    """
    Medical office/clinic model representing a practice location.

    Supports multi-tenant architecture where each user can have multiple offices.
    Manages WhatsApp integration, Google Calendar sync, and appointment settings.
    """

    __tablename__ = "offices"

    # Primary Key
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    # Multi-tenancy
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)

    # Basic Information
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    specialty: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    whatsapp_phone: Mapped[Optional[str]] = mapped_column(
        String(20), unique=True, nullable=True
    )
    owner_phone: Mapped[Optional[str]] = mapped_column(
        String(20), nullable=True
    )
    city: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    state: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    address: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    # WhatsApp Integration
    whatsapp_phone_id: Mapped[Optional[str]] = mapped_column(
        String(255), unique=True, nullable=True
    )
    whatsapp_waba_id: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True
    )
    whatsapp_token: Mapped[Optional[str]] = mapped_column(
        String(500), nullable=True
    )  # AES-256 encrypted
    whatsapp_mode: Mapped[Optional[str]] = mapped_column(
        String(50), nullable=True
    )  # coexistence|dedicated|new
    whatsapp_app_active: Mapped[bool] = mapped_column(Boolean, default=False)
    whatsapp_twilio_number_sid: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True
    )
    bot_paused_until: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # AI Assistant Settings
    assistant_tone: Mapped[str] = mapped_column(
        String(50), default="formal", nullable=False
    )
    assistant_name: Mapped[str] = mapped_column(
        String(100), default="Assistant", nullable=False
    )
    custom_prompt: Mapped[Optional[str]] = mapped_column(
        String(5000), nullable=True
    )
    welcome_message: Mapped[Optional[str]] = mapped_column(
        String(2000), nullable=True
    )

    # Appointment Duration & Pricing
    new_patient_duration_min: Mapped[int] = mapped_column(
        Integer, default=30, nullable=False
    )
    returning_patient_duration_min: Mapped[int] = mapped_column(
        Integer, default=30, nullable=False
    )
    new_patient_cost: Mapped[Optional[str]] = mapped_column(
        String(100), nullable=True
    )
    returning_patient_cost: Mapped[Optional[str]] = mapped_column(
        String(100), nullable=True
    )

    # Google Calendar Integration
    google_calendar_token: Mapped[Optional[dict]] = mapped_column(
        JSONB, nullable=True
    )  # encrypted
    google_calendar_id: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True
    )
    google_watch_channel_id: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True
    )
    google_watch_expiry: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Status & Plan
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    onboarding_completed: Mapped[bool] = mapped_column(Boolean, default=False)
    plan: Mapped[str] = mapped_column(String(50), default="trial", nullable=False)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=func.now(), nullable=False
    )
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), onupdate=func.now(), nullable=True
    )

    # Relationships
    availability_schedules: Mapped[List[AvailabilitySchedule]] = relationship(
        "AvailabilitySchedule",
        back_populates="office",
        cascade="all, delete-orphan",
        foreign_keys="AvailabilitySchedule.office_id",
    )
    time_blocks: Mapped[List[TimeBlock]] = relationship(
        "TimeBlock",
        back_populates="office",
        cascade="all, delete-orphan",
        foreign_keys="TimeBlock.office_id",
    )
    patients: Mapped[List[Patient]] = relationship(
        "Patient",
        back_populates="office",
        cascade="all, delete-orphan",
        foreign_keys="Patient.office_id",
    )
    appointments: Mapped[List[Appointment]] = relationship(
        "Appointment",
        back_populates="office",
        cascade="all, delete-orphan",
        foreign_keys="Appointment.office_id",
    )
    conversations: Mapped[List[Conversation]] = relationship(
        "Conversation",
        back_populates="office",
        cascade="all, delete-orphan",
        foreign_keys="Conversation.office_id",
    )
    waitlist: Mapped[List[Waitlist]] = relationship(
        "Waitlist",
        back_populates="office",
        cascade="all, delete-orphan",
        foreign_keys="Waitlist.office_id",
    )
    google_calendar_events: Mapped[List[GoogleCalendarEvent]] = relationship(
        "GoogleCalendarEvent",
        back_populates="office",
        cascade="all, delete-orphan",
        foreign_keys="GoogleCalendarEvent.office_id",
    )

    def __repr__(self) -> str:
        return f"<Office(id={self.id}, name={self.name}, user_id={self.user_id})>"


class AvailabilitySchedule(Base):
    """
    Weekly availability schedule for an office.

    Defines working hours for each day of the week with appointment duration
    and buffer time settings.
    """

    __tablename__ = "availability_schedules"

    # Primary Key
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    # Foreign Key
    office_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("offices.id", ondelete="CASCADE"),
        nullable=False,
    )

    # Schedule Details
    day_of_week: Mapped[int] = mapped_column(
        Integer, nullable=False
    )  # 0=Sun, 1=Mon, ..., 6=Sat
    start_time: Mapped[time] = mapped_column(Time, nullable=False)
    end_time: Mapped[time] = mapped_column(Time, nullable=False)

    # Duration Settings
    appointment_duration_min: Mapped[int] = mapped_column(Integer, default=30)
    buffer_minutes: Mapped[int] = mapped_column(Integer, default=10)

    # Status
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    # Relationship
    office: Mapped[Office] = relationship(
        "Office",
        back_populates="availability_schedules",
        foreign_keys=[office_id],
    )

    def __repr__(self) -> str:
        return f"<AvailabilitySchedule(id={self.id}, day={self.day_of_week}, start={self.start_time})>"


class TimeBlock(Base):
    """
    Time blocks when an office is unavailable.

    Can represent vacations, meetings, lunch breaks, or Google Calendar blocks.
    Supports recurring blocks and synced blocks from Google Calendar.
    """

    __tablename__ = "time_blocks"

    # Primary Key
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    # Foreign Key
    office_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("offices.id", ondelete="CASCADE"),
        nullable=False,
    )

    # Block Details
    start_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reason: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    # Block Type
    is_all_day: Mapped[bool] = mapped_column(Boolean, default=False)
    is_recurring: Mapped[bool] = mapped_column(Boolean, default=False)

    # Google Calendar Integration
    origin: Mapped[str] = mapped_column(
        String(50), default="manual", nullable=False
    )  # manual|google_calendar
    google_event_id: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True
    )

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=func.now(), nullable=False
    )

    # Relationship
    office: Mapped[Office] = relationship(
        "Office",
        back_populates="time_blocks",
        foreign_keys=[office_id],
    )

    def __repr__(self) -> str:
        return f"<TimeBlock(id={self.id}, reason={self.reason})>"


class Patient(Base):
    """
    Patient/client record for an office.

    Tracks contact information, interaction history, and consultation statistics.
    """

    __tablename__ = "patients"

    # Primary Key
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    # Foreign Key
    office_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("offices.id", ondelete="CASCADE"),
        nullable=False,
    )

    # Basic Information
    name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    phone: Mapped[str] = mapped_column(String(20), nullable=False)
    whatsapp_id: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # WhatsApp Business API ID
    email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    date_of_birth: Mapped[Optional[date]] = mapped_column(Date, nullable=True)

    # Additional Information
    primary_reason: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    how_they_found_us: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    internal_notes: Mapped[Optional[str]] = mapped_column(
        String(2000), nullable=True
    )

    # Status & Statistics
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    first_appointment_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_appointment_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    total_appointments: Mapped[int] = mapped_column(Integer, default=0)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=func.now(), nullable=False
    )

    # Relationships
    appointments: Mapped[List[Appointment]] = relationship(
        "Appointment",
        back_populates="patient",
        cascade="all, delete-orphan",
        foreign_keys="Appointment.patient_id",
    )
    conversations: Mapped[List[Conversation]] = relationship(
        "Conversation",
        back_populates="patient",
        cascade="all, delete-orphan",
        foreign_keys="Conversation.patient_id",
    )
    waitlist: Mapped[List[Waitlist]] = relationship(
        "Waitlist",
        back_populates="patient",
        cascade="all, delete-orphan",
        foreign_keys="Waitlist.patient_id",
    )
    office: Mapped[Office] = relationship(
        "Office",
        foreign_keys=[office_id],
    )

    def __repr__(self) -> str:
        return f"<Patient(id={self.id}, name={self.name}, phone={self.phone})>"


class Appointment(Base):
    """
    Appointment record linking patients to time slots.

    Manages appointment lifecycle including scheduling, reminders, cancellations,
    and follow-ups. Can sync with Google Calendar.
    """

    __tablename__ = "appointments"

    # Primary Key
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    # Foreign Keys
    office_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("offices.id", ondelete="CASCADE"),
        nullable=False,
    )
    patient_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("patients.id", ondelete="CASCADE"),
        nullable=False,
    )

    # Appointment Timing
    start_datetime: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_datetime: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False)

    # Appointment Details
    type: Mapped[str] = mapped_column(
        String(50), default="first_visit", nullable=False
    )
    consultation_reason: Mapped[Optional[str]] = mapped_column(
        String(500), nullable=True
    )

    # Status & Notes
    status: Mapped[str] = mapped_column(
        String(50), default="scheduled", nullable=False
    )  # scheduled|confirmed|attended|no_show|cancelled
    post_consultation_notes: Mapped[Optional[str]] = mapped_column(
        String(2000), nullable=True
    )
    instructions: Mapped[Optional[str]] = mapped_column(
        String(2000), nullable=True
    )

    # Cancellation & Rescheduling
    cancelled_by: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    cancellation_reason: Mapped[Optional[str]] = mapped_column(
        String(500), nullable=True
    )
    rescheduled_from: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("appointments.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Reminders & Follow-ups
    reminder_morning_sent: Mapped[bool] = mapped_column(Boolean, default=False)
    reminder_4h_sent: Mapped[bool] = mapped_column(Boolean, default=False)
    reminder_1h_sent: Mapped[bool] = mapped_column(Boolean, default=False)
    reminder_15m_sent: Mapped[bool] = mapped_column(Boolean, default=False)
    follow_up_sent: Mapped[bool] = mapped_column(Boolean, default=False)
    confirmation_request_sent: Mapped[bool] = mapped_column(Boolean, default=False)

    # Google Calendar Integration
    google_event_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=func.now(), nullable=False
    )
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), onupdate=func.now(), nullable=True
    )

    # Relationships
    office: Mapped[Office] = relationship(
        "Office",
        back_populates="appointments",
        foreign_keys=[office_id],
    )
    patient: Mapped[Patient] = relationship(
        "Patient",
        back_populates="appointments",
        foreign_keys=[patient_id],
    )
    rescheduling_from: Mapped[Optional[Appointment]] = relationship(
        "Appointment",
        remote_side=[id],
        foreign_keys=[rescheduled_from],
        backref="rescheduled_to",
    )

    def __repr__(self) -> str:
        return f"<Appointment(id={self.id}, patient_id={self.patient_id}, start_datetime={self.start_datetime})>"


class Conversation(Base):
    """
    WhatsApp conversation thread between office and patient.

    Tracks conversation state, current intent, and medical takeover status.
    """

    __tablename__ = "conversations"

    # Primary Key
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    # Foreign Keys
    office_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("offices.id", ondelete="CASCADE"),
        nullable=False,
    )
    patient_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("patients.id", ondelete="SET NULL"),
        nullable=True,
    )

    # WhatsApp Information
    whatsapp_id: Mapped[str] = mapped_column(String(50), nullable=False)

    # Conversation State
    status: Mapped[str] = mapped_column(
        String(50), default="active", nullable=False
    )  # active|paused|archived
    current_intent: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True
    )  # schedule_appointment|confirm_appointment|provide_information|follow_up
    context: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)

    # Medical Takeover
    taken_by_doctor: Mapped[bool] = mapped_column(Boolean, default=False)
    doctor_took_control_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Activity Tracking
    last_message_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=func.now(), nullable=False
    )

    # Relationships
    office: Mapped[Office] = relationship(
        "Office",
        back_populates="conversations",
        foreign_keys=[office_id],
    )
    patient: Mapped[Optional[Patient]] = relationship(
        "Patient",
        back_populates="conversations",
        foreign_keys=[patient_id],
    )
    messages: Mapped[List[Message]] = relationship(
        "Message",
        back_populates="conversation",
        cascade="all, delete-orphan",
        foreign_keys="Message.conversation_id",
    )

    def __repr__(self) -> str:
        return f"<Conversation(id={self.id}, whatsapp_id={self.whatsapp_id})>"


class Message(Base):
    """
    Individual message in a WhatsApp conversation.

    Stores message content, direction (inbound/outbound), type, and metadata.
    """

    __tablename__ = "messages"

    # Primary Key
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    # Foreign Key
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
    )

    # Message Content
    content: Mapped[str] = mapped_column(String(4000), nullable=False)

    # Message Type & Direction
    type: Mapped[str] = mapped_column(
        String(50), default="text", nullable=False
    )  # text|image|document|audio|video
    direction: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # incoming|outgoing

    # Message Attributes
    is_doctor_echo: Mapped[bool] = mapped_column(Boolean, default=False)
    whatsapp_message_id: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True
    )

    # Metadata
    extra_metadata: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=func.now(), nullable=False
    )

    # Relationship
    conversation: Mapped[Conversation] = relationship(
        "Conversation",
        back_populates="messages",
        foreign_keys=[conversation_id],
    )

    def __repr__(self) -> str:
        return f"<Message(id={self.id}, type={self.type}, direction={self.direction})>"


class Waitlist(Base):
    """
    Waiting list entry for patients seeking appointments.

    Tracks patient preferences for scheduling and urgency level.
    """

    __tablename__ = "waitlist"

    # Primary Key
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    # Foreign Keys
    office_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("offices.id", ondelete="CASCADE"),
        nullable=False,
    )
    patient_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("patients.id", ondelete="CASCADE"),
        nullable=False,
    )

    # Preferences
    preferred_days: Mapped[Optional[list]] = mapped_column(
        ARRAY(Integer), nullable=True
    )  # Array of weekday numbers
    preferred_time: Mapped[str] = mapped_column(
        String(50), default="any", nullable=False
    )

    # Status
    is_urgent: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(
        String(50), default="active", nullable=False
    )  # active|contacted|scheduled|cancelled

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=func.now(), nullable=False
    )

    # Relationships
    office: Mapped[Office] = relationship(
        "Office",
        back_populates="waitlist",
        foreign_keys=[office_id],
    )
    patient: Mapped[Patient] = relationship(
        "Patient",
        back_populates="waitlist",
        foreign_keys=[patient_id],
    )

    def __repr__(self) -> str:
        return f"<Waitlist(id={self.id}, patient_id={self.patient_id})>"


class GoogleCalendarEvent(Base):
    """
    Synced Google Calendar event for appointment tracking.

    Tracks bidirectional sync between system appointments and Google Calendar.
    Can represent appointments or time blocks.
    """

    __tablename__ = "google_calendar_events"

    # Primary Key
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    # Foreign Keys
    office_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("offices.id", ondelete="CASCADE"),
        nullable=False,
    )
    appointment_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("appointments.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Google Calendar Details
    google_event_id: Mapped[str] = mapped_column(String(255), nullable=False)
    title: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    is_block: Mapped[bool] = mapped_column(Boolean, default=False)

    # Event Timing
    start_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # Sync Tracking
    synced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=func.now(), nullable=False
    )
    content_hash: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # Relationships
    office: Mapped[Office] = relationship(
        "Office",
        back_populates="google_calendar_events",
        foreign_keys=[office_id],
    )
    appointment: Mapped[Optional[Appointment]] = relationship(
        "Appointment",
        foreign_keys=[appointment_id],
    )

    def __repr__(self) -> str:
        return f"<GoogleCalendarEvent(id={self.id}, google_event_id={self.google_event_id})>"


# Create indexes for common queries
__all__ = [
    "Office",
    "AvailabilitySchedule",
    "TimeBlock",
    "Patient",
    "Appointment",
    "Conversation",
    "Message",
    "Waitlist",
    "GoogleCalendarEvent",
]
