"""Spanish wording for the write-audit alerts (Rule 12).

The doctor gets these when what the system said it did doesn't match what is
actually stored. Tone is plain and specific: what happened, on which
appointment, and what to check. No apology, no jargon, and never a claim we
haven't verified.
"""

from __future__ import annotations

from datetime import datetime

from app.core.constants import DAYS_ES, MX_TIMEZONE


def format_slot(dt: datetime) -> str:
    """Format an appointment datetime as 'lunes 16/06/2025 a las 16:00' (MX TZ)."""
    dt = dt.astimezone(MX_TIMEZONE) if dt.tzinfo else dt.replace(tzinfo=MX_TIMEZONE)
    return f"{DAYS_ES[dt.weekday()]} {dt.strftime('%d/%m/%Y')} a las {dt.strftime('%H:%M')}"


def doctor_sync_warning(patient_name: str, slot: str, detail: str) -> str:
    """Alert: a stored appointment doesn't match what the action reported."""
    return (
        f"Aviso de revisión: en la cita de {patient_name} del {slot}, {detail}.\n\n"
        f"Conviene que lo verifiques antes de que llegue el paciente."
    )
