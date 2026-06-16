"""Spanish message builders for the urgency flow.

These are product-facing strings (Spanish, by design). The doctor notification
and the patient confirmations are sent by the system (Celery tasks / tool
handlers), so wording is deterministic here rather than left to the LLM.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from app.core.constants import DAYS_ES


def _is_formal(tone: str) -> bool:
    return tone == "formal"


def format_datetime(dt: datetime) -> str:
    """'viernes 16/06 a las 17:00' (assumes a Mexico-local datetime)."""
    return f"{DAYS_ES[dt.weekday()]} {dt.strftime('%d/%m')} a las {dt.strftime('%H:%M')}"


def format_preferred(preferred_time: Optional[datetime]) -> str:
    """Human label for the patient's requested time, or 'lo antes posible'."""
    if preferred_time is None:
        return "lo antes posible"
    return format_datetime(preferred_time)


def doctor_urgency_notification(patient_name: str, reason: str, preferred: str) -> str:
    """Free-text alert to the doctor (sent while their 24h window is open)."""
    return (
        "Solicitud de cita URGENTE.\n\n"
        f"Paciente: {patient_name}\n"
        f"Motivo: {reason}\n"
        f"Horario solicitado: {preferred}\n\n"
        "Respóndeme con el día y la hora para aprobarla, o dime que no puedes atenderla."
    )


def patient_urgency_approved(
    formatted: str, office_name: str, office_address: Optional[str], tone: str = "informal"
) -> str:
    """Confirmation to the patient once the doctor approves the urgent slot."""
    address = f"\nDirección: {office_address}" if office_address else ""
    if _is_formal(tone):
        return (
            f"Buenas noticias: el doctor lo puede atender de urgencia el {formatted}. "
            f"Lo esperamos en {office_name}.{address}"
        )
    return (
        f"¡Buenas noticias! El doctor te puede atender de urgencia el {formatted}. "
        f"Te esperamos en {office_name}.{address}"
    )


def patient_urgency_rejected(tone: str = "informal") -> str:
    """Message to the patient when the doctor declines the urgent request."""
    if _is_formal(tone):
        return (
            "Lo siento, por el momento el doctor no puede atenderlo de urgencia. "
            "¿Desea que le ayude a agendar en el horario disponible más próximo?"
        )
    return (
        "Lo siento, por el momento el doctor no puede atenderte de urgencia. "
        "¿Quieres que te ayude a agendar en el horario disponible más próximo?"
    )


def patient_urgency_timeout(slots_text: str, tone: str = "informal") -> str:
    """Fallback to the patient when the doctor did not respond in time."""
    formal = _is_formal(tone)
    if slots_text:
        intro = (
            "Disculpe la demora. Por ahora no pude confirmar una atención de urgencia, "
            "pero estos son los horarios disponibles más próximos:"
            if formal
            else
            "Disculpa la demora. Por ahora no pude confirmar una atención de urgencia, "
            "pero estos son los horarios disponibles más próximos:"
        )
        question = "¿Cuál le acomoda?" if formal else "¿Cuál te acomoda?"
        return f"{intro}\n{slots_text}\n{question}"
    if formal:
        return (
            "Disculpe la demora. Por ahora no pude confirmar una atención de urgencia. "
            "¿Desea que le ayude a buscar el horario disponible más próximo?"
        )
    return (
        "Disculpa la demora. Por ahora no pude confirmar una atención de urgencia. "
        "¿Quieres que te ayude a buscar el horario disponible más próximo?"
    )


def format_slots_list(slots: list) -> str:
    """Number a few AvailableSlot objects for the timeout message."""
    lines = []
    for i, slot in enumerate(slots, start=1):
        lines.append(f"{i}. {format_datetime(slot.start_time)}")
    return "\n".join(lines)
