"""WhatsApp message template definitions (Meta-approved HSM templates).

Business-initiated messages (reminders, confirmations, follow-ups, doctor
alerts) sent outside the 24h customer service window MUST use a pre-approved
template — free text is rejected by Meta. This module is the single source of
truth for them: the names the senders use, the exact body each one is created
with (`TEMPLATE_SPECS`), and the parameter builders the Celery tasks call.

Templates live per WABA. Embedded Signup connects the doctor's own WABA, which
starts with none of ours, so `whatsapp/template_provisioning.py` creates every
spec below on it and tracks its approval status. A body change therefore needs
a NEW name (Meta does not let an approved template be silently rewritten): bump
the `_vN` suffix, and the daily sync creates it everywhere.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from dataclasses import dataclass, field
from typing import Dict, List, Tuple

from app.core.constants import DAYS_ES

# Template language code as registered in Meta (Spanish - Mexico).
TEMPLATE_LANGUAGE = "es_MX"

# Template names, as created on every office's WABA (see TEMPLATE_SPECS).
TEMPLATE_OFFICE_MESSAGE = "office_message_v3"
TEMPLATE_FOLLOW_UP = "appointment_follow_up_v3"
# Day-before confirmation; quick replies Confirmar / Cancelar / Reagendar. A tap
# arrives as an incoming message of type "button" whose text is the title.
TEMPLATE_CONFIRMATION_DAY_BEFORE = "appointment_confirmation_day_before_v3"
TEMPLATE_REMINDER = "appointment_reminder_v3"
# Waiting-room check-in at the appointment's start time when the patient's 24h
# window is closed (in-window it goes out as interactive buttons instead).
TEMPLATE_ARRIVAL_CHECK_IN = "arrival_check_in_v2"
# Doctor-facing "alert that opens the window": the doctor replies and the bot
# can then send the urgency details as free text.
TEMPLATE_URGENCY_ALERT = "urgency_alert_v3"
# Doctor-facing notice that a cita moved.
TEMPLATE_RESCHEDULE_NOTICE = "reschedule_notice_v3"
# Doctor-facing notifications (configurable per office), sent when the doctor's
# 24h window is closed. In-window the same events go out as free text.
TEMPLATE_DOCTOR_NEW_APPOINTMENT = "doctor_new_appointment_v3"
TEMPLATE_DOCTOR_NEW_PATIENT_APPOINTMENT = "doctor_new_patient_appointment_v3"
TEMPLATE_DOCTOR_CANCELLATION = "doctor_cancellation_v2"
TEMPLATE_DOCTOR_NEW_PATIENT = "doctor_new_patient_v2"
TEMPLATE_DOCTOR_DAILY_AGENDA = "doctor_daily_agenda"
# Only for "arrived"; "on the way" has no template and goes out in-window only.
TEMPLATE_DOCTOR_PATIENT_ARRIVED = "doctor_patient_arrived_v4"
TEMPLATE_DOCTOR_SYNC_WARNING = "doctor_sync_warning_v2"
TEMPLATE_DOCTOR_APPOINTMENT_BRIEF = "doctor_appointment_brief_v2"
# Google rejected the office's calendar credentials.
TEMPLATE_DOCTOR_CALENDAR_DISCONNECTED = "doctor_calendar_disconnected_v3"
# The doctor moved or deleted a cita in Google Calendar: the system applied it
# and asks before telling the patient.
TEMPLATE_DOCTOR_CALENDAR_CHANGE = "doctor_calendar_change_v2"


@dataclass(frozen=True)
class TemplateSpec:
    """One template exactly as it is created on a WABA.

    Meta's rules the bodies follow (tests/unit/test_wa_template_specs.py
    enforces them): no body starts or ends with a variable, no two variables
    are adjacent, and every {{name}} has an example value.
    """

    name: str
    body: str
    examples: Dict[str, str]
    quick_replies: Tuple[str, ...] = field(default_factory=tuple)
    category: str = "UTILITY"


_EX_PATIENT = "María López"
_EX_LOCATION = "Consultorio Dra. Ruiz, Av. Juárez 120"
_EX_SLOT = "viernes 3 de mayo a las 10:30 AM"

TEMPLATE_SPECS: Tuple[TemplateSpec, ...] = (
    # ---- Patient-facing ----------------------------------------------------
    TemplateSpec(
        TEMPLATE_OFFICE_MESSAGE,
        # Free text from the office: the wording ties it to the patient's care
        # so Meta files it as UTILITY (v2 was reclassified as MARKETING).
        "Hola {{patient_name}}, tiene un aviso de {{location}} sobre su atención: "
        "{{text}} Puede responder a este mensaje si tiene alguna duda.",
        {
            "patient_name": _EX_PATIENT,
            "location": _EX_LOCATION,
            "text": "Su cita del viernes 3 de mayo se cambió a las 12:00 PM.",
        },
    ),
    TemplateSpec(
        TEMPLATE_FOLLOW_UP,
        "Hola {{patient_name}}, gracias por tu visita en {{location}}. ¿Cómo te has "
        "sentido? Si tienes preguntas o necesitas algo, escríbenos — estamos para "
        "ayudarte.",
        {"patient_name": _EX_PATIENT, "location": _EX_LOCATION},
    ),
    TemplateSpec(
        TEMPLATE_CONFIRMATION_DAY_BEFORE,
        "Hola {{patient_name}}, te escribimos de {{location}} para confirmar tu cita "
        "de mañana {{appointment_date}} a las {{appointment_time}}. Saludos.",
        {
            "patient_name": _EX_PATIENT,
            "location": _EX_LOCATION,
            "appointment_date": "viernes 3 de mayo",
            "appointment_time": "10:30 AM",
        },
        quick_replies=("Confirmar", "Cancelar", "Reagendar"),
    ),
    TemplateSpec(
        TEMPLATE_REMINDER,
        "Hola {{patient_name}}, te recordamos que tienes cita {{appointment_date}} a "
        "las {{appointment_time}} en {{location}}. ¡Te esperamos!",
        {
            "patient_name": _EX_PATIENT,
            "appointment_date": "mañana",
            "appointment_time": "10:30 AM",
            "location": _EX_LOCATION,
        },
    ),
    TemplateSpec(
        TEMPLATE_ARRIVAL_CHECK_IN,
        "Hola {{patient_name}}, es la hora de su cita en {{location}}. ¿Ya se "
        "encuentra aquí? Avísenos para que el doctor le reciba.",
        {"patient_name": _EX_PATIENT, "location": "Consultorio Dra. Ruiz"},
        # Same titles as the in-window interactive buttons, so a tap reads the
        # same to the assistant whichever path delivered the question.
        quick_replies=("Ya llegué", "Voy en camino"),
    ),
    # ---- Doctor-facing -----------------------------------------------------
    TemplateSpec(
        TEMPLATE_URGENCY_ALERT,
        "Tienes una solicitud de cita urgente de {{patient_name}} pendiente. "
        "Esperamos tus indicaciones.",
        {"patient_name": _EX_PATIENT},
    ),
    TemplateSpec(
        TEMPLATE_RESCHEDULE_NOTICE,
        "El paciente {{patient_name}} cambió de horario. Su nueva cita es el "
        "{{new_slot}}, y el espacio anterior quedó libre.",
        {"patient_name": _EX_PATIENT, "new_slot": _EX_SLOT},
    ),
    TemplateSpec(
        TEMPLATE_DOCTOR_NEW_APPOINTMENT,
        "El paciente {{patient_name}} agendó cita para el {{slot}} — ya es paciente "
        "conocido del consultorio.",
        {"patient_name": _EX_PATIENT, "slot": _EX_SLOT},
    ),
    TemplateSpec(
        TEMPLATE_DOCTOR_NEW_PATIENT_APPOINTMENT,
        "Se registró un paciente nuevo, {{patient_name}}, con cita el {{slot}}. Es su "
        "primera visita al consultorio.",
        {"patient_name": _EX_PATIENT, "slot": _EX_SLOT},
    ),
    TemplateSpec(
        TEMPLATE_DOCTOR_CANCELLATION,
        "El paciente {{patient_name}} canceló su cita del {{slot}}. El espacio quedó libre.",
        {"patient_name": _EX_PATIENT, "slot": _EX_SLOT},
    ),
    TemplateSpec(
        TEMPLATE_DOCTOR_NEW_PATIENT,
        "Se registró un nuevo paciente: {{patient_name}}. Ya está en tu lista.",
        {"patient_name": _EX_PATIENT},
    ),
    TemplateSpec(
        TEMPLATE_DOCTOR_DAILY_AGENDA,
        "Buen día. Hoy tienes {{count}} cita(s): {{detail}}. Responde a este mensaje "
        "si necesitas mover algo.",
        {
            "count": "3",
            "detail": "10:00 AM María López; 11:00 AM Juan Pérez (sin confirmar); "
            "1:00 PM Ana Gómez",
        },
    ),
    TemplateSpec(
        TEMPLATE_DOCTOR_PATIENT_ARRIVED,
        "El paciente {{patient_name}} avisó: {{detail}}. ¿Lo hacemos pasar?",
        {"patient_name": _EX_PATIENT, "detail": "ya llegó a su cita de las 10:30 AM"},
    ),
    TemplateSpec(
        TEMPLATE_DOCTOR_SYNC_WARNING,
        "Aviso sobre la cita de {{patient_name}}: {{detail}}. Conviene revisarla.",
        {
            "patient_name": _EX_PATIENT,
            "detail": "la cita no aparece en tu Google Calendar",
        },
    ),
    TemplateSpec(
        TEMPLATE_DOCTOR_APPOINTMENT_BRIEF,
        # v1 was reclassified as MARKETING; this wording reads as an agenda notice.
        "Aviso de agenda: en unos minutos tienes cita con {{patient_name}}. Datos de "
        "la cita: {{detail}}. Responde a este mensaje si necesitas mover la cita.",
        {
            "patient_name": _EX_PATIENT,
            "detail": "10:30 AM, primera vez, motivo: dolor de rodilla",
        },
    ),
    TemplateSpec(
        TEMPLATE_DOCTOR_CALENDAR_DISCONNECTED,
        "Tu Google Calendar se desconectó de ArgosAI. Sigo agendando citas con la "
        "agenda del sistema, pero no veo los eventos que tengas solo en Google. "
        "Reconéctalo aquí: {{detail}} y las citas agendadas mientras tanto se "
        "agregarán a tu calendario.",
        {"detail": "https://argosai.mx/dashboard/settings"},
    ),
    TemplateSpec(
        TEMPLATE_DOCTOR_CALENDAR_CHANGE,
        "Vi un cambio en tu Google Calendar en la cita de {{patient_name}}: "
        "{{detail}}. ¿Le aviso al paciente? Respóndeme por aquí.",
        {
            "patient_name": _EX_PATIENT,
            "detail": "la moviste al viernes 3 de mayo a las 12:00 PM",
        },
    ),
)

# Set to False if the templates were created with positional params ({{1}}, {{2}})
# instead of named params ({{patient_name}}). Named is the modern default and
# matches how these templates were written.
USE_NAMED_PARAMS = True

# Spanish month names, index 0 = January (datetime.month is 1-based).
MONTHS_ES = [
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
]


def _param(name: str, value: str) -> Dict[str, str]:
    """Build a single template body parameter, named or positional.

    Meta rejects a parameter containing a newline, a tab or more than four
    consecutive spaces (error 132018), and free text — a doctor's message, a
    waitlist offer — often has line breaks. They are folded into single spaces.
    """
    param: Dict[str, str] = {"type": "text", "text": " ".join(value.split())}
    if USE_NAMED_PARAMS:
        param["parameter_name"] = name
    return param


def format_explicit_date(appointment_local: datetime) -> str:
    """Always 'viernes 3 de mayo' (no hoy/mañana shortcut).

    Used by templates whose copy already says 'mañana', where a relative word
    would read awkwardly ('tu cita de mañana mañana').
    """
    return (
        f"{DAYS_ES[appointment_local.weekday()]} "
        f"{appointment_local.day} de {MONTHS_ES[appointment_local.month - 1]}"
    )


def format_appointment_date(appointment_local: datetime, now_local: datetime) -> str:
    """Format a date for patients as 'hoy', 'mañana' or 'viernes 3 de mayo'."""
    appt_date = appointment_local.date()
    today = now_local.date()
    if appt_date == today:
        return "hoy"
    if appt_date == today + timedelta(days=1):
        return "mañana"
    return format_explicit_date(appointment_local)


def build_reminder_params(
    patient_name: str, appointment_date: str, appointment_time: str, location: str
) -> List[Dict[str, str]]:
    """appointment_reminder: patient_name, appointment_date, appointment_time, location."""
    return [
        _param("patient_name", patient_name),
        _param("appointment_date", appointment_date),
        _param("appointment_time", appointment_time),
        _param("location", location),
    ]


def build_confirmation_params(
    patient_name: str, location: str, appointment_date: str, appointment_time: str
) -> List[Dict[str, str]]:
    """appointment_confirmation_day_before: patient_name, location, appointment_date, appointment_time."""
    return [
        _param("patient_name", patient_name),
        _param("location", location),
        _param("appointment_date", appointment_date),
        _param("appointment_time", appointment_time),
    ]


def build_follow_up_params(
    patient_name: str, location: str
) -> List[Dict[str, str]]:
    """appointment_follow_up: patient_name, location."""
    return [
        _param("patient_name", patient_name),
        _param("location", location),
    ]


def build_office_message_params(
    patient_name: str, location: str, text: str
) -> List[Dict[str, str]]:
    """office_message: patient_name, location, text (free message body)."""
    return [
        _param("patient_name", patient_name),
        _param("location", location),
        _param("text", text),
    ]


def build_arrival_check_params(
    patient_name: str, location: str
) -> List[Dict[str, str]]:
    """arrival_check_in: patient_name, location."""
    return [
        _param("patient_name", patient_name),
        _param("location", location),
    ]


def build_doctor_patient_arrived_params(
    patient_name: str, detail: str
) -> List[Dict[str, str]]:
    """doctor_patient_arrived: patient_name, detail (status + brief, one line)."""
    return [
        _param("patient_name", patient_name),
        _param("detail", detail),
    ]


def build_urgency_alert_params(patient_name: str) -> List[Dict[str, str]]:
    """urgency_alert: patient_name (doctor-facing alert that opens the window)."""
    return [
        _param("patient_name", patient_name),
    ]


def build_reschedule_notice_params(
    patient_name: str, new_slot: str
) -> List[Dict[str, str]]:
    """reschedule_notice: patient_name, new_slot (doctor-facing reschedule alert)."""
    return [
        _param("patient_name", patient_name),
        _param("new_slot", new_slot),
    ]


def build_doctor_new_appointment_params(
    patient_name: str, slot: str
) -> List[Dict[str, str]]:
    """doctor_new_appointment: patient_name, slot."""
    return [
        _param("patient_name", patient_name),
        _param("slot", slot),
    ]


def build_doctor_new_patient_appointment_params(
    patient_name: str, slot: str
) -> List[Dict[str, str]]:
    """doctor_new_patient_appointment: patient_name, slot (new patient + first appt)."""
    return [
        _param("patient_name", patient_name),
        _param("slot", slot),
    ]


def build_doctor_cancellation_params(
    patient_name: str, slot: str
) -> List[Dict[str, str]]:
    """doctor_cancellation: patient_name, slot."""
    return [
        _param("patient_name", patient_name),
        _param("slot", slot),
    ]


def build_doctor_new_patient_params(patient_name: str) -> List[Dict[str, str]]:
    """doctor_new_patient: patient_name."""
    return [
        _param("patient_name", patient_name),
    ]


def build_doctor_sync_warning_params(
    patient_name: str, detail: str
) -> List[Dict[str, str]]:
    """doctor_sync_warning: patient_name, detail (what diverged, one line)."""
    return [
        _param("patient_name", patient_name),
        _param("detail", detail),
    ]


def build_doctor_calendar_change_params(
    patient_name: str, detail: str
) -> List[Dict[str, str]]:
    """doctor_calendar_change: patient_name, detail (what changed, one line)."""
    return [
        _param("patient_name", patient_name),
        _param("detail", detail),
    ]


def build_doctor_calendar_disconnected_params(detail: str) -> List[Dict[str, str]]:
    """doctor_calendar_disconnected: detail (where to reconnect)."""
    return [_param("detail", detail)]


def build_doctor_appointment_brief_params(
    patient_name: str, detail: str
) -> List[Dict[str, str]]:
    """doctor_appointment_brief: patient_name, detail (the brief in one line)."""
    return [
        _param("patient_name", patient_name),
        _param("detail", detail),
    ]


def build_doctor_daily_agenda_params(count: str, detail: str) -> List[Dict[str, str]]:
    """doctor_daily_agenda: count (today's citas), detail (the citas on one line)."""
    return [
        _param("count", count),
        _param("detail", detail),
    ]
