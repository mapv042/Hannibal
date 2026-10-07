"""Spanish free-text builders for the configurable doctor notifications.

Sent by the system (Celery tasks) while the doctor's 24h window is open; out of
window the equivalent approved Meta templates are used (see wa_templates.py).
Wording is deterministic here and tone-aware via office.assistant_tone, mirroring
app/modules/urgencies/templates.py.
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from app.core.constants import MX_TIMEZONE
from app.utils.dates import long_date_label, time_label


def _is_formal(tone: str) -> bool:
    return tone == "formal"


def format_slot(dt: datetime) -> str:
    """Format an appointment datetime as 'lunes 16/06/2025 a las 16:00' (MX TZ)."""
    dt = dt.astimezone(MX_TIMEZONE) if dt.tzinfo else dt.replace(tzinfo=MX_TIMEZONE)
    return f"{long_date_label(dt.date())} a las {time_label(dt)}"


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


def doctor_patient_arrived(
    patient_name: str,
    arrival_status: str,
    eta_minutes: int | None,
    brief_lines: List[str],
    tone: str = "informal",
) -> str:
    """Alert: the patient answered the waiting-room check-in.

    Carries the pre-consultation brief in the same message rather than sending a
    second one — this is the moment the doctor needs it, and it's the last point
    where a wrong detail can still be caught before the patient walks in.
    """
    if arrival_status == "arrived":
        headline = f"{patient_name} ya está en el consultorio."
    elif eta_minutes:
        headline = f"{patient_name} viene en camino, llega en unos {eta_minutes} minutos."
    else:
        headline = f"{patient_name} viene en camino."

    if not brief_lines:
        return headline
    body = "\n".join(f"• {line}" for line in brief_lines)
    return f"{headline}\n\n{body}"


def arrival_detail(arrival_status: str, eta_minutes: int | None) -> str:
    """One-line arrival state for the out-of-window template parameter."""
    if arrival_status == "arrived":
        return "ya está en el consultorio"
    if eta_minutes:
        return f"viene en camino, llega en unos {eta_minutes} minutos"
    return "viene en camino"


def agenda_line(slot: str, patient_name: str, first_visit: bool, unconfirmed: bool) -> str:
    """One cita of the day summary: "9:00 AM — María García (primera vez) · sin confirmar"."""
    line = f"{slot} — {patient_name}"
    if first_visit:
        line += " (primera vez)"
    if unconfirmed:
        line += " · sin confirmar"
    return line


def doctor_daily_agenda(
    lines: List[str],
    pending_urgencies: int,
    free_slots: Optional[int],
    tone: str = "informal",
) -> str:
    """Morning summary of the doctor's day, sent before their first block.

    Replaces the old "citas sin confirmar" digest: that was one slice of what
    the doctor wants to know on the way to the practice.
    """
    count = len(lines)
    if count:
        noun = "cita" if count == 1 else "citas"
        parts = [f"Buen día. Tu agenda de hoy ({count} {noun}):", *[f"• {l}" for l in lines]]
    else:
        parts = ["Buen día. Hoy no tienes citas agendadas."]
    if pending_urgencies:
        noun = "solicitud urgente" if pending_urgencies == 1 else "solicitudes urgentes"
        parts.append(f"Tienes {pending_urgencies} {noun} esperando tu respuesta.")
    if free_slots is not None:
        parts.append(
            "No quedan horarios libres hoy."
            if free_slots == 0
            else f"Quedan {free_slots} horario{'s' if free_slots != 1 else ''} libre{'s' if free_slots != 1 else ''} hoy."
        )
    closing = "Si necesita mover algo, dígamelo por aquí." if _is_formal(tone) else "Si necesitas mover algo, dímelo por aquí."
    parts.append(closing)
    return "\n".join(parts)


def daily_agenda_detail(lines: List[str], limit: int = 700) -> str:
    """The day's citas on one line, for the Meta template param (no newlines)."""
    detail = "; ".join(lines) or "sin citas agendadas"
    return detail if len(detail) <= limit else detail[: limit - 1].rstrip() + "…"


def doctor_reschedule(
    patient_name: str, old_slot: str, new_slot: str, by_doctor_cancellation: bool
) -> str:
    """Alert: an appointment moved.

    `by_doctor_cancellation` distinguishes the two ways this happens: the doctor
    cancelled a slot and the patient answered by rebooking (the doctor is
    waiting on that answer), or the patient moved their own appointment
    unprompted (news to the doctor).
    """
    lead = (
        f"{patient_name} reagendó la cita que cancelaste."
        if by_doctor_cancellation
        else f"{patient_name} movió su cita."
    )
    return f"{lead}\n\nAntes: {old_slot}\nAhora: {new_slot}"


def doctor_appointment_brief(
    patient_name: str, slot_time: str, brief_lines: List[str]
) -> str:
    """Pre-consultation brief, sent shortly before the appointment starts.

    Same content as the brief carried by the arrival alert, but it does not
    depend on the patient answering the check-in: the doctor gets it whether or
    not the patient replies, which is the whole point of walking in prepared.
    """
    headline = f"En unos minutos ({slot_time}) tienes cita con {patient_name}."
    if not brief_lines:
        return headline
    body = "\n".join(f"• {line}" for line in brief_lines)
    return f"{headline}\n\n{body}"


def brief_detail(brief_lines: List[str]) -> str:
    """One-line brief for the out-of-window template parameter."""
    return "; ".join(brief_lines) if brief_lines else "sin notas previas"
