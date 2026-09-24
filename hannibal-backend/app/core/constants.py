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


class AssistantGender(str, Enum):
    """Grammatical gender the assistant uses when referring to itself.

    Spanish forces a choice on every adjective the assistant applies to itself
    ("listo"/"lista"), so renaming the assistant from a feminine default to a
    masculine or neutral name without telling the model leaves it disagreeing
    with itself mid-conversation.
    """

    FEMININE = "femenino"
    MASCULINE = "masculino"
    NEUTRAL = "neutro"


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
    HOLIDAY = "holiday"  # Seeded Mexican statutory holiday


# Time Preference
class TimePreference(str, Enum):
    """Patient's preferred time of day."""

    MORNING = "morning"  # Morning
    AFTERNOON = "afternoon"  # Afternoon
    ANY = "any"  # Any time


# Reminder Configuration
class ReminderType(str, Enum):
    """Per-office reminder kinds. Timing is configurable via ReminderRule."""

    WEEK_BEFORE = "week_before"  # Week before the appointment
    DAY_BEFORE = "day_before"  # Day before: reminder + confirm/cancel buttons
    SIX_HOURS = "6h"  # 6 hours before
    DOCTOR_BRIEF = "doctor_brief"  # Pre-consultation brief, to the DOCTOR
    AT_TIME = "at_time"  # At appointment time: the waiting-room check-in
    POST_APPOINTMENT = "post_appointment"  # After the appointment (follow-up)


# Default reminder rules applied to every office unless overridden.
# offset_minutes is signed relative to the appointment start:
#   negative = before the appointment, positive = after.
# Doctors with a full agenda need more lead time than a same-day nudge, so the
# "before" reminders are a week, a day and six hours out.
DEFAULT_REMINDER_RULES: list[tuple[ReminderType, int]] = [
    (ReminderType.WEEK_BEFORE, -10080),  # 7 days before
    (ReminderType.DAY_BEFORE, -1440),  # 24h before
    (ReminderType.SIX_HOURS, -360),  # 6h before
    (ReminderType.DOCTOR_BRIEF, -15),  # 15 min before: the doctor's brief
    (ReminderType.AT_TIME, 0),  # at the appointment time: "¿ya llegaste?"
    (ReminderType.POST_APPOINTMENT, 120),  # 2h after
]

# Bounds for a configurable offset: at most a week before, a day after. The
# scheduler's sending window (Rule 15) still decides the hour of day.
MIN_REMINDER_OFFSET = -10080
MAX_REMINDER_OFFSET = 1440

# Maps each reminder type to the Appointment idempotency flag that records
# whether it has already been sent.
SENT_FLAG_BY_REMINDER_TYPE: dict[str, str] = {
    ReminderType.WEEK_BEFORE.value: "reminder_week_before_sent",
    ReminderType.DAY_BEFORE.value: "reminder_day_before_sent",
    ReminderType.SIX_HOURS.value: "reminder_6h_sent",
    ReminderType.DOCTOR_BRIEF.value: "doctor_brief_sent",
    ReminderType.AT_TIME.value: "arrival_check_sent",
    ReminderType.POST_APPOINTMENT.value: "follow_up_sent",
}


# Waiting room: how the patient answered the check-in sent at appointment time.
class ArrivalStatus(str, Enum):
    """Patient's reported state for an appointment that has just started."""

    ON_THE_WAY = "on_the_way"  # Reported they're on their way
    ARRIVED = "arrived"  # Reported they're at the office
    NO_ANSWER = "no_answer"  # Check-in sent, patient never replied


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
MONTHS_ES = [
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
]
