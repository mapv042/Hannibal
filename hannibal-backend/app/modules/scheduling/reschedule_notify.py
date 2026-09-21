"""Linking a patient's new booking to a slot the DOCTOR cancelled.

When the doctor cancels an appointment and asks the patient to rebook, the
patient's next booking is an answer the doctor is waiting on. This module finds
that pending cancellation and links the new appointment to it through
`Appointment.rescheduled_from`; the notification itself is sent by
`app.modules.notifications.service.notify_reschedule`, which covers every
reschedule rather than only this case.

Rule 13 lives here too: if the patient cancels outright instead of rebooking,
the doctor has to hear how it actually ended.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional
from uuid import UUID

import redis.asyncio as aioredis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import DAYS_ES, MX_TIMEZONE
from app.db.models import Appointment, Office, Patient
from app.modules.reminders.wa_templates import (
    TEMPLATE_RESCHEDULE_NOTICE,
    build_reschedule_notice_params,
)
from app.modules.whatsapp.doctor_notify import send_doctor_alert
from app.utils.dates import now_mx
from app.utils.logger import get_logger

logger = get_logger(__name__)

# Only treat a doctor cancellation as "awaiting reschedule" if it happened
# recently — avoids linking an unrelated old cancellation to a fresh booking.
PENDING_CANCELLATION_LOOKBACK_DAYS = 14


def _format_slot(dt: datetime) -> str:
    """Format an appointment datetime as 'lunes 16/06/2025 a las 16:00' (MX TZ)."""
    dt = dt.astimezone(MX_TIMEZONE) if dt.tzinfo else dt.replace(tzinfo=MX_TIMEZONE)
    return f"{DAYS_ES[dt.weekday()]} {dt.strftime('%d/%m/%Y')} a las {dt.strftime('%H:%M')}"


def _doctor_gave_up_text(patient_name: str, old_slot: str) -> str:
    """Free-text alert: the patient walked away instead of rescheduling."""
    return (
        f"{patient_name} no reagendó la cita que cancelaste ({old_slot}): "
        f"decidió cancelar en definitiva.\n\n"
        f"Si quieres recuperarlo, avísame y le escribo."
    )


async def find_pending_doctor_cancellation(
    db: AsyncSession,
    office_id,
    patient_id,
    exclude_appointment_id=None,
) -> Optional[Appointment]:
    """The doctor cancellation this patient still hasn't answered, if any.

    Shared by the two outcomes a doctor cancellation can have: the patient
    rebooks (link_pending_doctor_cancellation) or the patient gives up
    (Rule 13 — the doctor has to hear about that one too, or they keep believing
    the patient is coming back).
    """
    cutoff = now_mx() - timedelta(days=PENDING_CANCELLATION_LOOKBACK_DAYS)

    conditions = [
        Appointment.office_id == office_id,
        Appointment.patient_id == patient_id,
        Appointment.status == "cancelled",
        Appointment.cancelled_by == "doctor",
        Appointment.start_datetime >= cutoff,
    ]
    if exclude_appointment_id is not None:
        conditions.append(Appointment.id != exclude_appointment_id)

    result = await db.execute(
        select(Appointment)
        .where(*conditions)
        .order_by(Appointment.start_datetime.desc())
    )

    for cancelled in result.scalars().all():
        # Skip cancellations already answered by a reschedule.
        already_linked = await db.execute(
            select(Appointment.id)
            .where(Appointment.rescheduled_from == cancelled.id)
            .limit(1)
        )
        if already_linked.scalar_one_or_none() is None:
            return cancelled
    return None


async def link_pending_doctor_cancellation(
    db: AsyncSession, new_appointment: Appointment
) -> bool:
    """Link a fresh patient booking to a pending doctor cancellation, if any.

    Looks for the most recent appointment of the same patient/office that the
    DOCTOR cancelled, was upcoming/recent, and has not yet been answered by a
    reschedule. If found, sets new_appointment.rescheduled_from to it (the marker
    that distinguishes "reschedule after doctor cancellation" from a normal
    booking) and returns True. Otherwise a no-op returning False.
    """
    cancelled = await find_pending_doctor_cancellation(
        db,
        new_appointment.office_id,
        new_appointment.patient_id,
        exclude_appointment_id=new_appointment.id,
    )
    if cancelled is None:
        return False

    new_appointment.rescheduled_from = cancelled.id
    await db.flush()
    logger.info(
        "reschedule_linked_to_doctor_cancellation",
        new_appointment_id=str(new_appointment.id),
        cancelled_appointment_id=str(cancelled.id),
    )
    return True


async def notify_doctor_of_abandoned_reschedule(
    db: AsyncSession,
    redis_client: aioredis.Redis,
    meta_client,
    cancelled_appointment_id: UUID,
) -> str:
    """Rule 13: report that a doctor-requested reschedule ended in a cancellation.

    The doctor cancelled a cita and asked the patient to rebook; the patient
    instead cancelled outright. Without this the doctor only sees the generic
    cancellation notice — or nothing, if that toggle is off — and keeps a slot
    mentally reserved for someone who isn't coming back.
    """
    cancelled = await db.get(Appointment, cancelled_appointment_id)
    if not cancelled:
        return "not_found"

    office = await db.get(Office, cancelled.office_id)
    patient = (
        await db.get(Patient, cancelled.patient_id) if cancelled.patient_id else None
    )
    if not office or not patient:
        return "skipped"
    patient_name = patient.name or "El paciente"
    old_slot = _format_slot(cancelled.start_datetime)

    return await send_doctor_alert(
        redis_client,
        meta_client,
        office,
        text=_doctor_gave_up_text(patient_name, old_slot),
        # Reuses the reschedule_notice template: same shape (patient + slot),
        # and the free-text path carries the nuance when the window is open.
        template_name=TEMPLATE_RESCHEDULE_NOTICE,
        template_params=build_reschedule_notice_params(
            patient_name, f"canceló en definitiva ({old_slot})"
        ),
        log_event="abandoned_reschedule_notify_doctor",
    )
