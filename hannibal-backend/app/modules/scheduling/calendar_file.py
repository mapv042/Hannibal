"""Add-to-calendar file (.ics) for a patient's cita.

After a booking or a reschedule the patient gets a button that opens this
file: on iPhone it goes straight to "Agregar al calendario", on Android the
calendar app opens it. WhatsApp can't carry the .ics itself (text/calendar is
not among Meta's document types), so the button points at a public endpoint and
the link is signed instead of authenticated.

The file holds only what is on the practice's door — where, when, how to reach
it. No patient name and no reason: it ends up in a phone calendar that may sync
anywhere, and the reason is health data.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.security import sign_link_value
from app.db.models import Appointment, Office
from app.utils.dates import real_now
from app.utils.phone import display_or_raw

CALENDAR_LINK_PURPOSE = "appointment-ics"

# A phone alarm on top of the WhatsApp reminders: the one that fires while the
# patient is already out of the house.
ALARM_MINUTES_BEFORE = 60

# RFC 5545: content lines longer than 75 octets are folded.
_MAX_LINE_OCTETS = 75


def calendar_link(appointment_id: uuid.UUID | str) -> Optional[str]:
    """Public, signed address of the cita's .ics; None when BACKEND_URL is unset."""
    if not settings.backend_url:
        return None
    value = str(appointment_id)
    signature = sign_link_value(CALENDAR_LINK_PURPOSE, value)
    base = settings.backend_url.rstrip("/")
    return f"{base}/api/public/calendar/{value}/{signature}/cita.ics"


async def chain_root(db: AsyncSession, appointment: Appointment) -> tuple[uuid.UUID, int]:
    """The first appointment of a reschedule chain, and how many moves followed.

    The root id is the event's UID, so the file sent after a reschedule updates
    the event the patient already added instead of leaving the old time behind
    as a second event. The move count becomes SEQUENCE, which tells the calendar
    app this version is newer.
    """
    current = appointment
    seen = {current.id}
    moves = 0
    while current.rescheduled_from and current.rescheduled_from not in seen:
        previous = await db.get(Appointment, current.rescheduled_from)
        if previous is None or previous.office_id != appointment.office_id:
            break
        seen.add(previous.id)
        current = previous
        moves += 1
    return current.id, moves


def build_ics(
    appointment: Appointment,
    office: Office,
    uid: uuid.UUID | str,
    sequence: int = 0,
) -> str:
    """The VCALENDAR text (CRLF line endings) for one cita."""
    summary = f"Cita en {office.name}"
    location = (office.address or "").strip() or office.name
    if office.whatsapp_phone:
        contact = (
            "Para cambiar o cancelar la cita, escribe al WhatsApp del consultorio: "
            f"{display_or_raw(office.whatsapp_phone)}"
        )
    else:
        contact = "Para cambiar o cancelar la cita, escribe al WhatsApp del consultorio."

    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Hannibal//Citas//ES",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "BEGIN:VEVENT",
        f"UID:{uid}@hannibal",
        f"SEQUENCE:{sequence}",
        f"DTSTAMP:{_utc(real_now())}",
        f"DTSTART:{_utc(appointment.start_datetime)}",
        f"DTEND:{_utc(appointment.end_datetime)}",
        f"SUMMARY:{_escape(summary)}",
        f"LOCATION:{_escape(location)}",
        f"DESCRIPTION:{_escape(contact)}",
        "STATUS:CONFIRMED",
        "BEGIN:VALARM",
        "ACTION:DISPLAY",
        f"DESCRIPTION:{_escape(summary)}",
        f"TRIGGER:-PT{ALARM_MINUTES_BEFORE}M",
        "END:VALARM",
        "END:VEVENT",
        "END:VCALENDAR",
    ]
    return "".join(_fold(line) + "\r\n" for line in lines)


def _utc(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _escape(text: str) -> str:
    """RFC 5545 TEXT escaping."""
    return (
        text.replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\r\n", "\\n")
        .replace("\n", "\\n")
    )


def _fold(line: str) -> str:
    """Fold at 75 octets without splitting a UTF-8 character ("Cita en Clínica…")."""
    parts, current, size = [], "", 0
    for ch in line:
        width = len(ch.encode("utf-8"))
        # Continuation lines start with a space, which counts toward their 75.
        limit = _MAX_LINE_OCTETS if not parts else _MAX_LINE_OCTETS - 1
        if size + width > limit:
            parts.append(current)
            current, size = "", 0
        current += ch
        size += width
    parts.append(current)
    return "\r\n ".join(parts)
