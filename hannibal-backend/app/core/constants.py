from __future__ import annotations

from enum import Enum
from zoneinfo import ZoneInfo


# WhatsApp Integration Mode
class WhatsAppMode(str, Enum):
    """WhatsApp integration mode for office."""

    COEXISTENCE = "coexistence"  # Coexist with existing flows
    DEDICATED = "dedicated"  # Dedicated WhatsApp only
    NEW = "new"  # New WhatsApp integration


# Assistant Tone
class AssistantTone(str, Enum):
    """Tone of the AI assistant."""

    FORMAL = "formal"
    INFORMAL = "informal"


# Subscription Plans
class SubscriptionPlan(str, Enum):
    """Available subscription plans."""

    TRIAL = "trial"
    STARTER = "starter"
    PRO = "pro"


# Appointment Types
class AppointmentType(str, Enum):
    """Type of medical appointment."""

    FIRST_VISIT = "first_visit"  # First-time visit
    FOLLOW_UP = "follow_up"  # Follow-up visit
    URGENT = "urgent"  # Emergency
    VIRTUAL = "virtual"  # Virtual consultation


# Appointment Status
class AppointmentStatus(str, Enum):
    """Status of a scheduled appointment."""

    SCHEDULED = "scheduled"  # Scheduled
    CONFIRMED = "confirmed"  # Confirmed
    CANCELLED = "cancelled"  # Cancelled
    COMPLETED = "completed"  # Completed
    NO_SHOW = "no_show"  # Patient didn't show up


# Cancellation Reason
class CancelledBy(str, Enum):
    """Who cancelled the appointment."""

    PATIENT = "patient"  # Patient
    OFFICE = "office"  # Office
    SYSTEM = "system"  # System


# Conversation Status
class ConversationStatus(str, Enum):
    """Status of a conversation with a patient."""

    ACTIVE = "active"  # Active
    WAITING_CONFIRMATION = "waiting_confirmation"  # Waiting for confirmation
    PAUSED_BY_DOCTOR = "paused_by_doctor"  # Paused by doctor
    COMPLETED = "completed"  # Completed
    ABANDONED = "abandoned"  # Abandoned


# Message Type
class MessageType(str, Enum):
    """Type of message in conversation."""

    TEXT = "text"  # Text
    AUDIO = "audio"  # Audio
    IMAGE = "image"  # Image
    DOCUMENT = "document"  # Document
    ECHO = "echo"  # Echo/confirmation


# Message Direction
class MessageDirection(str, Enum):
    """Direction of message flow."""

    INCOMING = "incoming"  # Incoming
    OUTGOING = "outgoing"  # Outgoing


# Block Origin
class BlockOrigin(str, Enum):
    """Source of time block."""

    MANUAL = "manual"  # Manually blocked
    GOOGLE_CALENDAR = "google_calendar"  # Blocked via calendar


# Waiting List Status
class WaitlistStatus(str, Enum):
    """Status of patient in waiting list."""

    ACTIVE = "active"  # Active in waiting list
    CONTACTED = "contacted"  # Contacted
    SCHEDULED = "scheduled"  # Scheduled
    CANCELLED = "cancelled"  # Cancelled


# Time Preference
class TimePreference(str, Enum):
    """Patient's preferred time of day."""

    MORNING = "morning"  # Morning
    AFTERNOON = "afternoon"  # Afternoon
    ANY = "any"  # Any time


# Intent Recognition
class Intent(str, Enum):
    """Patient intent extracted from message."""

    SCHEDULE = "SCHEDULE"  # Schedule appointment
    CANCEL = "CANCEL"  # Cancel appointment
    RESCHEDULE = "RESCHEDULE"  # Reschedule appointment
    CONFIRM = "CONFIRM"  # Confirm appointment
    QUESTION = "QUESTION"  # General question
    URGENT = "URGENT"  # Emergency
    GREETING = "GREETING"  # Greeting
    OTHER = "OTHER"  # Other


# Mexico City Timezone
MX_TIMEZONE = ZoneInfo("America/Mexico_City")

# Spanish day names (Monday=0 … Sunday=6, matching datetime.weekday())
DAYS_ES = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
