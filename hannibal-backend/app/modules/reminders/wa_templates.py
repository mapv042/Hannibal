"""WhatsApp message template definitions (Meta-approved HSM templates).

Business-initiated messages (reminders, confirmations, follow-ups) sent outside
the 24h customer service window MUST use a pre-approved template — free text is
rejected by Meta. This module centralizes the template names, language code and
parameter builders so the Celery tasks just call build_*_params().

The template NAMES and parameter ORDER here must match exactly what is approved
in the WhatsApp Manager. Current approved templates (language es_MX):

  office_message                      -> patient_name, location, text
  appointment_follow_up               -> patient_name, location
  appointment_confirmation_day_before -> patient_name, location, appointment_date, appointment_time
  appointment_reminder                -> patient_name, appointment_date, appointment_time, location
  urgency_alert                       -> patient_name   (doctor-facing, out-of-window)
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Dict, List

from app.core.constants import DAYS_ES

# Template language code as registered in Meta (Spanish - Mexico).
TEMPLATE_LANGUAGE = "es_MX"

# Approved template names. Keep in sync with the WhatsApp Manager.
TEMPLATE_OFFICE_MESSAGE = "office_message"
TEMPLATE_FOLLOW_UP = "appointment_follow_up"
TEMPLATE_CONFIRMATION_DAY_BEFORE = "appointment_confirmation_day_before"
TEMPLATE_REMINDER = "appointment_reminder"
# Doctor-facing "alert that opens the window": sent to the doctor's WhatsApp
# when their 24h window is closed, so they reply and the bot can then send the
# urgency details as free text. Suggested body:
#   "Tienes una solicitud de cita urgente de {{patient_name}} pendiente.
#    Responde a este mensaje para gestionarla."
TEMPLATE_URGENCY_ALERT = "urgency_alert"
# Doctor-facing notice sent when a patient reschedules a slot the DOCTOR had
# cancelled, and the doctor's 24h window is closed. Lets the doctor see how the
# freed slot ended up. Suggested body:
#   "{{patient_name}} reagendó su cita. Nueva cita: {{new_slot}}.
#    Responde aquí si necesitas ajustarla."
TEMPLATE_RESCHEDULE_NOTICE = "reschedule_notice"

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
    """Build a single template body parameter, named or positional."""
    param: Dict[str, str] = {"type": "text", "text": value}
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
