"""Changes the doctor makes to a cita directly in Google Calendar.

The doctor's calendar is where they rearrange their day, so moving or deleting
a cita there must reach the system: before this, inbound sync skipped the
events Hannibal created, the appointment stayed at the old time, the patient
kept getting reminders for it and the old slot stayed taken.

Now a move becomes a reschedule (new row, `rescheduled_from`, adopting the
event the doctor already moved) and a deletion becomes a cancellation — applied
at once, so reminders and the assistant use the right time. What is NOT done
at once is telling the patient: a drag in a calendar can be a slip, so the
doctor is asked first (`gcal_change_pending:*` → the doctor prompt's
CAMBIOS EN TU CALENDARIO → the `resolve_calendar_change` tool).
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Optional

import redis.asyncio as aioredis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import BookedVia
from app.db.models import Appointment, Office, Patient
from app.modules.ai.tool_helpers import format_appointment_dt, localize_mx
from app.modules.audit.tasks import enqueue_write_audit
from app.modules.scheduling.availability import release_slot_lock
from app.modules.scheduling.booking import book_appointment
from app.utils.dates import now_mx
from app.utils.logger import get_logger

logger = get_logger(__name__)

PENDING_KEY = "gcal_change_pending:{office_id}"
PENDING_TTL_SECONDS = 24 * 3600

MOVED = "moved"
CANCELLED = "cancelled"

ACTIVE_STATUSES = ("scheduled", "confirmed")


def _parse_event_time(node: dict) -> tuple[Optional[datetime], bool]:
    """(aware datetime, all_day) from a Google start/end node."""
    if "dateTime" in node:
        return datetime.fromisoformat(node["dateTime"].replace("Z", "+00:00")), False
    if "date" in node:
        return None, True
    return None, False


async def appointment_for_event(
    db: AsyncSession, office_id: uuid.UUID, event_id: str
) -> Optional[Appointment]:
    """The cita behind one of our Google events, preferring the live one."""
    rows = (
        await db.execute(
            select(Appointment)
            .where(
                Appointment.office_id == office_id,
                Appointment.google_event_id == event_id,
            )
            .order_by(Appointment.created_at.desc())
        )
    ).scalars().all()
    for row in rows:
        if row.status in ACTIVE_STATUSES:
            return row
    return rows[0] if rows else None


async def apply_calendar_change(
    db: AsyncSession,
    office: Office,
    appointment: Appointment,
    event: dict,
    redis_client: aioredis.Redis,
) -> Optional[dict]:
    """Bring a cita in line with its Google event. Returns a notice, or None.

    Echoes of our own writes arrive here too (a cancellation marks the event
    transparent, a reschedule creates a new event), so anything that already
    matches the row — or a cita that is no longer active — is a no-op.
    """
    if appointment.status not in ACTIVE_STATUSES:
        return None

    patient = await db.get(Patient, appointment.patient_id)
    patient_name = (patient.name if patient else None) or "Paciente"
    old_label = format_appointment_dt(appointment.start_datetime)

    if event.get("status") == "cancelled":
        return await _cancel_from_calendar(db, office, appointment, patient_name, old_label, redis_client)

    # A "free" (transparent) event is how we mark our own cancellations; a
    # doctor does not free a cita that way, so it is not treated as one.
    if event.get("transparency") == "transparent":
        return None

    start, all_day = _parse_event_time(event.get("start") or {})
    end, _ = _parse_event_time(event.get("end") or {})
    if all_day or start is None:
        return None
    if start == appointment.start_datetime:
        return None
    if start <= now_mx():
        logger.info(
            "gcal_move_to_past_ignored",
            office_id=str(office.id),
            appointment_id=str(appointment.id),
        )
        return None

    duration = appointment.duration_minutes or 30
    if end is not None and end > start:
        duration = int((end - start).total_seconds() // 60)

    return await _move_from_calendar(
        db, office, appointment, event["id"], start, duration, patient_name, old_label, redis_client
    )


async def _cancel_from_calendar(
    db: AsyncSession,
    office: Office,
    appointment: Appointment,
    patient_name: str,
    old_label: str,
    redis_client: aioredis.Redis,
) -> dict:
    appointment.status = "cancelled"
    appointment.cancelled_by = "doctor"
    appointment.cancellation_reason = "Eliminada en Google Calendar"
    # The event is gone; nothing left for the audit to "repair".
    appointment.google_event_id = None
    await _release(office.id, appointment.start_datetime, redis_client)
    enqueue_write_audit(appointment.id, "cancel", status="cancelled")

    logger.info(
        "gcal_deletion_cancelled_appointment",
        office_id=str(office.id),
        appointment_id=str(appointment.id),
    )
    return {
        "id": uuid.uuid4().hex[:8],
        "kind": CANCELLED,
        "appointment_id": str(appointment.id),
        "patient_name": patient_name,
        "old_label": old_label,
        "new_label": None,
    }


async def _move_from_calendar(
    db: AsyncSession,
    office: Office,
    appointment: Appointment,
    event_id: str,
    new_start: datetime,
    duration: int,
    patient_name: str,
    old_label: str,
    redis_client: aioredis.Redis,
) -> dict:
    # The doctor moved it on purpose: another cita or a Google-only event at the
    # new time is their call (overridable); a block or closed hours are not.
    outcome = await book_appointment(
        db,
        office,
        patient_id=appointment.patient_id,
        start_dt=new_start,
        duration_min=duration,
        reason=appointment.consultation_reason or "Consulta",
        appt_type=appointment.type,
        gcal_title="",
        gcal_description="",
        redis_client=redis_client,
        allow_conflict=True,
        booked_by_patient_id=appointment.booked_by_patient_id,
        intake_notes=appointment.intake_notes,
        rescheduled_from=appointment.id,
        booked_via=BookedVia.GOOGLE_CALENDAR.value,
        existing_google_event_id=event_id,
    )
    new_label = format_appointment_dt(new_start)
    if outcome.error:
        logger.warning(
            "gcal_move_rejected",
            office_id=str(office.id),
            appointment_id=str(appointment.id),
            reason=outcome.error,
        )
        return {
            "id": uuid.uuid4().hex[:8],
            "kind": "rejected",
            "appointment_id": str(appointment.id),
            "patient_name": patient_name,
            "old_label": old_label,
            "new_label": new_label,
            "reason": outcome.error,
        }

    new_appointment = outcome.appointment
    # Carry what already happened for this visit: a confirmed cita the doctor
    # only shifted is still confirmed.
    new_appointment.status = appointment.status
    appointment.status = "cancelled"
    appointment.cancelled_by = "doctor"
    appointment.cancellation_reason = "Movida en Google Calendar"
    # The event now belongs to the new row. Leaving it on the old one would let
    # the write audit "repair" it as a cancelled cita's event — un-booking the
    # appointment the doctor just moved.
    appointment.google_event_id = None
    await _release(office.id, appointment.start_datetime, redis_client)

    enqueue_write_audit(
        new_appointment.id,
        "reschedule",
        start_datetime=new_start,
        status=new_appointment.status,
        patient_id=new_appointment.patient_id,
    )
    enqueue_write_audit(appointment.id, "cancel", status="cancelled")

    logger.info(
        "gcal_move_rescheduled_appointment",
        office_id=str(office.id),
        old_id=str(appointment.id),
        new_id=str(new_appointment.id),
    )
    return {
        "id": uuid.uuid4().hex[:8],
        "kind": MOVED,
        "appointment_id": str(new_appointment.id),
        "patient_name": patient_name,
        "old_label": old_label,
        "new_label": new_label,
    }


async def _release(office_id: uuid.UUID, start: datetime, redis_client: aioredis.Redis) -> None:
    try:
        await release_slot_lock(office_id, start, redis_client)
    except Exception as e:
        logger.warning("gcal_change_slot_release_failed", error=str(e))


# --------------------------------------------------------------------------- #
# Pending notices: the doctor decides whether the patient is told
# --------------------------------------------------------------------------- #


async def store_pending(
    redis_client: aioredis.Redis, office_id: uuid.UUID, notices: list[dict]
) -> None:
    key = PENDING_KEY.format(office_id=office_id)
    for notice in notices:
        await redis_client.hset(key, notice["id"], json.dumps(notice))
    await redis_client.expire(key, PENDING_TTL_SECONDS)


async def get_pending(redis_client: aioredis.Redis, office_id: uuid.UUID) -> list[dict]:
    """Changes awaiting the doctor's "¿le aviso?", oldest-looking first."""
    try:
        raw = await redis_client.hgetall(PENDING_KEY.format(office_id=office_id))
    except Exception as e:
        logger.warning("gcal_change_pending_read_failed", error=str(e))
        return []
    notices = []
    for value in raw.values():
        try:
            notices.append(json.loads(value))
        except (TypeError, ValueError):
            continue
    return sorted(notices, key=lambda n: n.get("old_label") or "")


async def pop_pending(
    redis_client: aioredis.Redis, office_id: uuid.UUID, notice_id: str
) -> Optional[dict]:
    key = PENDING_KEY.format(office_id=office_id)
    raw = await redis_client.hget(key, notice_id)
    if raw is None:
        return None
    await redis_client.hdel(key, notice_id)
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return None


def describe(notice: dict) -> str:
    """One Spanish line: what changed, for the doctor alert and the prompt."""
    if notice["kind"] == MOVED:
        return f"la moviste del {notice['old_label']} al {notice['new_label']}"
    if notice["kind"] == CANCELLED:
        return f"la borraste (era el {notice['old_label']}); ya quedó cancelada"
    return (
        f"la moviste del {notice['old_label']} al {notice['new_label']}, pero no pude "
        f"cambiarla en el sistema: {notice.get('reason', '')}"
    )


async def alert_doctor(
    redis_client: aioredis.Redis, meta_client, office: Office, notices: list[dict]
) -> None:
    """Tell the doctor what their calendar edit did, and ask before telling the patient."""
    from app.modules.reminders.wa_templates import (
        TEMPLATE_DOCTOR_CALENDAR_CHANGE,
        build_doctor_calendar_change_params,
    )
    from app.modules.whatsapp.doctor_notify import send_doctor_alert

    for notice in notices:
        detail = describe(notice)
        if notice["kind"] == "rejected":
            text = (
                f"Vi un cambio en tu Google Calendar en la cita de {notice['patient_name']}: "
                f"{detail}. En el sistema sigue el {notice['old_label']}. Regrésala en tu "
                f"calendario o dime a qué hora la muevo."
            )
        else:
            text = (
                f"Vi un cambio en tu Google Calendar en la cita de {notice['patient_name']}: "
                f"{detail}. ¿Le aviso al paciente?"
            )
        await send_doctor_alert(
            redis_client,
            meta_client,
            office,
            text=text,
            template_name=TEMPLATE_DOCTOR_CALENDAR_CHANGE,
            template_params=build_doctor_calendar_change_params(notice["patient_name"], detail),
            log_event="doctor_calendar_change_alert",
        )
