"""Rule 12 — verify that what an action said it did is what actually got stored.

A language model cannot reliably notice it misunderstood something, but it *can*
be checked against hard data. So this module doesn't try to grade Sofía's prose:
it takes what the action believed it wrote and compares it against the two
systems of record — the appointments table and the doctor's Google Calendar.

The failure this exists to catch is silent by construction: `book_appointment`
swallows Google Calendar errors so a hiccup there can't cost the patient their
booking (see scheduling/booking.py). That's the right trade at booking time, but
it leaves an appointment that exists for us and not for the doctor. Nobody finds
out until the patient walks in.

Divergences are reported to the doctor over WhatsApp, deduplicated so a
persistent problem is raised once a day rather than on every write.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional
from uuid import UUID

import redis.asyncio as aioredis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import MX_TIMEZONE
from app.db.models import Appointment, Office, Patient
from app.modules.audit import templates
from app.modules.google_calendar.service import get_calendar_event
from app.modules.reminders.wa_templates import (
    TEMPLATE_DOCTOR_SYNC_WARNING,
    build_doctor_sync_warning_params,
)
from app.modules.whatsapp.doctor_notify import send_doctor_alert
from app.utils.logger import get_logger

logger = get_logger(__name__)

# One alert per appointment per kind of divergence per day. A calendar that
# stays out of sync shouldn't page the doctor on every subsequent write.
ALERT_DEDUP_KEY = "audit_alert:{appointment_id}:{kind}"
ALERT_DEDUP_TTL_SECONDS = 24 * 60 * 60

# Google returns start times to the second; a sub-minute difference is rounding,
# not a real divergence.
TIME_TOLERANCE = timedelta(minutes=1)

# Divergence kinds, also used as the dedup key suffix.
KIND_ROW_MISSING = "row_missing"
KIND_FIELD_MISMATCH = "field_mismatch"
KIND_CALENDAR_MISSING = "calendar_missing"
KIND_CALENDAR_STALE = "calendar_stale"


@dataclass
class Divergence:
    """A concrete mismatch between what was intended and what is stored."""

    kind: str
    detail: str


def _parse_google_start(event: dict) -> Optional[datetime]:
    """Start datetime of a Google event, or None for an all-day/odd event."""
    raw = (event.get("start") or {}).get("dateTime")
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(MX_TIMEZONE)
    except ValueError:
        return None


async def _check_calendar(
    db: AsyncSession,
    office: Office,
    appointment: Appointment,
    expected_present: bool,
) -> Optional[Divergence]:
    """Compare the appointment against its Google Calendar event.

    `expected_present` is False for a cancellation: there the event should be
    gone or marked cancelled, and its continued presence is the divergence.
    """
    if not office.google_calendar_token:
        return None  # Nothing to reconcile against.

    if expected_present and not appointment.google_event_id:
        return Divergence(
            KIND_CALENDAR_MISSING,
            "la cita quedó guardada pero no se creó el evento en Google Calendar",
        )

    if not appointment.google_event_id:
        return None

    try:
        event = await get_calendar_event(
            office.id, appointment.google_event_id, db
        )
    except Exception as e:
        # Couldn't check is not the same as fine, but it isn't a divergence
        # either — don't cry wolf over a Google outage.
        logger.warning(
            "audit_calendar_unreadable",
            appointment_id=str(appointment.id),
            error=str(e),
        )
        return None

    if expected_present:
        if event is None or event.get("status") == "cancelled":
            return Divergence(
                KIND_CALENDAR_MISSING,
                "la cita está agendada pero su evento ya no existe en Google Calendar",
            )
        google_start = _parse_google_start(event)
        if google_start is not None:
            local_start = appointment.start_datetime.astimezone(MX_TIMEZONE)
            if abs(google_start - local_start) > TIME_TOLERANCE:
                return Divergence(
                    KIND_CALENDAR_STALE,
                    (
                        f"Google Calendar tiene la cita a las "
                        f"{google_start.strftime('%H:%M')} y el sistema a las "
                        f"{local_start.strftime('%H:%M')}"
                    ),
                )
        return None

    # Cancellation: the event should no longer occupy the slot.
    if event is not None and event.get("status") != "cancelled":
        return Divergence(
            KIND_CALENDAR_STALE,
            "la cita se canceló pero su evento sigue ocupando el horario en Google Calendar",
        )
    return None


def _check_row(appointment: Appointment, expectation: dict) -> Optional[Divergence]:
    """Compare the stored row against what the action believed it wrote."""
    expected_status = expectation.get("status")
    if expected_status and appointment.status != expected_status:
        return Divergence(
            KIND_FIELD_MISMATCH,
            (
                f"la cita quedó en estado '{appointment.status}' cuando "
                f"debía quedar en '{expected_status}'"
            ),
        )

    expected_start = expectation.get("start_datetime")
    if expected_start:
        try:
            wanted = datetime.fromisoformat(expected_start).astimezone(MX_TIMEZONE)
        except ValueError:
            wanted = None
        if wanted is not None:
            stored = appointment.start_datetime.astimezone(MX_TIMEZONE)
            if abs(stored - wanted) > TIME_TOLERANCE:
                return Divergence(
                    KIND_FIELD_MISMATCH,
                    (
                        f"la cita quedó guardada a las {stored.strftime('%H:%M')} "
                        f"y debía quedar a las {wanted.strftime('%H:%M')}"
                    ),
                )

    expected_patient = expectation.get("patient_id")
    if expected_patient and str(appointment.patient_id) != str(expected_patient):
        return Divergence(
            KIND_FIELD_MISMATCH, "la cita quedó guardada a nombre de otro paciente"
        )

    return None


async def _already_alerted(
    redis_client: aioredis.Redis, appointment_id: UUID, kind: str
) -> bool:
    """True if this divergence was already reported today (and mark it if not)."""
    key = ALERT_DEDUP_KEY.format(appointment_id=appointment_id, kind=kind)
    try:
        first = await redis_client.set(key, "1", nx=True, ex=ALERT_DEDUP_TTL_SECONDS)
        return not first
    except Exception as e:
        # A Redis blip must not swallow a real alert; risk a duplicate instead.
        logger.warning("audit_dedup_unavailable", error=str(e))
        return False


async def verify_appointment_write(
    db: AsyncSession,
    redis_client: aioredis.Redis,
    meta_client,
    appointment_id: UUID,
    expectation: dict,
) -> str:
    """Audit one appointment write. Returns "ok" | "diverged" | "not_found" | "skipped".

    "not_found" lets the Celery task retry: the tool handler's transaction
    commits after the task is enqueued, exactly as with the doctor notifications.
    """
    action = expectation.get("action", "escritura")

    appointment = await db.get(Appointment, appointment_id)
    if appointment is None:
        if action == "cancel":
            # A cancellation never deletes the row, so a missing one here is a
            # real problem, not a race — but we still can't tell the doctor
            # which appointment it was.
            return "not_found"
        return "not_found"

    office = await db.get(Office, appointment.office_id)
    if office is None:
        return "skipped"

    divergence = _check_row(appointment, expectation)
    if divergence is None:
        divergence = await _check_calendar(
            db, office, appointment, expected_present=action != "cancel"
        )

    if divergence is None:
        logger.info(
            "audit_write_ok",
            appointment_id=str(appointment_id),
            action=action,
        )
        return "ok"

    logger.error(
        "audit_write_diverged",
        appointment_id=str(appointment_id),
        action=action,
        kind=divergence.kind,
        detail=divergence.detail,
    )

    if await _already_alerted(redis_client, appointment_id, divergence.kind):
        return "diverged"

    patient = await db.get(Patient, appointment.patient_id)
    patient_name = (patient.name if patient else None) or "un paciente"
    slot = templates.format_slot(appointment.start_datetime)

    await send_doctor_alert(
        redis_client,
        meta_client,
        office,
        text=templates.doctor_sync_warning(patient_name, slot, divergence.detail),
        template_name=TEMPLATE_DOCTOR_SYNC_WARNING,
        template_params=build_doctor_sync_warning_params(
            patient_name, divergence.detail
        ),
        log_event="doctor_sync_warning",
    )
    return "diverged"
