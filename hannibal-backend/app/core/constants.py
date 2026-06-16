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


# Urgency Request Status
class UrgencyStatus(str, Enum):
    """Lifecycle of a patient urgent-appointment request awaiting doctor approval."""

    PENDING = "pending"  # Waiting for the doctor's decision
    APPROVED = "approved"  # Doctor approved and the urgent appointment was booked
    REJECTED = "rejected"  # Doctor declined the urgent request
    EXPIRED = "expired"  # Doctor did not respond within the timeout window


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


# Reminder Configuration
class ReminderType(str, Enum):
    """Per-office reminder kinds. Timing is configurable via ReminderRule."""

    DAY_BEFORE = "day_before"  # Day before the appointment
    FOUR_HOURS = "4h"  # 4 hours before
    ONE_HOUR = "1h"  # 1 hour before
    POST_APPOINTMENT = "post_appointment"  # After the appointment (follow-up)


# Default reminder rules applied to every office unless overridden.
# offset_minutes is signed relative to the appointment start:
#   negative = before the appointment, positive = after.
DEFAULT_REMINDER_RULES: list[tuple[ReminderType, int]] = [
    (ReminderType.DAY_BEFORE, -1440),  # 24h before
    (ReminderType.FOUR_HOURS, -240),  # 4h before
    (ReminderType.ONE_HOUR, -60),  # 1h before
    (ReminderType.POST_APPOINTMENT, 120),  # 2h after
]

# Maps each reminder type to the Appointment idempotency flag that records
# whether it has already been sent.
SENT_FLAG_BY_REMINDER_TYPE: dict[str, str] = {
    ReminderType.DAY_BEFORE.value: "reminder_day_before_sent",
    ReminderType.FOUR_HOURS.value: "reminder_4h_sent",
    ReminderType.ONE_HOUR.value: "reminder_1h_sent",
    ReminderType.POST_APPOINTMENT.value: "follow_up_sent",
}


# Urgency handling
# Minutes the bot waits for the doctor's approval of an urgent request before
# falling back to offering the patient the next normal available slot.
URGENCY_APPROVAL_TIMEOUT_MINUTES = 20

# Google Calendar color ids used per appointment state.
#   "9"  -> normal pending (light blue)   "10" -> confirmed (green)
#   "11" -> urgent (red)
GCAL_COLOR_URGENT = "11"


# Mexico City Timezone
MX_TIMEZONE = ZoneInfo("America/Mexico_City")

# Spanish day names (Monday=0 … Sunday=6, matching datetime.weekday())
DAYS_ES = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
