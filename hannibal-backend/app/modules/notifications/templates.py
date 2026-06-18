"""Spanish free-text builders for the configurable doctor notifications.

Sent by the system (Celery tasks) while the doctor's 24h window is open; out of
window the equivalent approved Meta templates are used (see wa_templates.py).
Wording is deterministic here and tone-aware via office.assistant_tone, mirroring
app/modules/urgencies/templates.py.
"""

from __future__ import annotations

from datetime import datetime
from typing import List

from app.core.constants import DAYS_ES, MX_TIMEZONE


def _is_formal(tone: str) -> bool:
    return tone == "formal"


def format_slot(dt: datetime) -> str:
    """Format an appointment datetime as 'lunes 16/06/2025 a las 16:00' (MX TZ)."""
    dt = dt.astimezone(MX_TIMEZONE) if dt.tzinfo else dt.replace(tzinfo=MX_TIMEZONE)
    return f"{DAYS_ES[dt.weekday()]} {dt.strftime('%d/%m/%Y')} a las {dt.strftime('%H:%M')}"


def doctor_new_appointment(patient_name: str, slot: str, tone: str = "informal") -> str:
    """Alert: the bot booked a new appointment for an existing patient."""
    if _is_formal(tone):
        return f"{patient_name} agendó una cita para el {slot}."
    return f"{patient_name} agendó una cita para el {slot}."


def doctor_new_patient_appointment(patient_name: str, slot: str, tone: str = "informal") -> str:
    """Combined alert: a brand-new patient booked their first appointment."""
    return (
        f"Nuevo paciente: {patient_name}.\n"
        f"Agendó su primera cita para el {slot}."
    )


def doctor_cancellation(patient_name: str, slot: str, tone: str = "informal") -> str:
    """Alert: a patient cancelled their appointment."""
    return f"{patient_name} canceló su cita del {slot}."


def doctor_new_patient(patient_name: str, tone: str = "informal") -> str:
    """Alert: a new patient was registered (without a booked appointment)."""
    return f"Nuevo paciente registrado: {patient_name}."


def doctor_unconfirmed_summary(slots: List[str], tone: str = "informal") -> str:
    """Morning digest: today's appointments still awaiting patient confirmation."""
    count = len(slots)
    noun = "cita" if count == 1 else "citas"
    header = f"Tienes {count} {noun} de hoy sin confirmar:"
    body = "\n".join(f"• {s}" for s in slots)
    return f"{header}\n{body}"
