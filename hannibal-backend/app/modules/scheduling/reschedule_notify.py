"""Notify the doctor when a patient reschedules a slot the doctor had cancelled.

When the doctor cancels an appointment and asks the patient to reschedule, the
patient's new booking should report back to the doctor how the freed slot ended
up. This module links the patient's new appointment to the doctor's cancelled
one (via Appointment.rescheduled_from) and sends the doctor a window-aware
WhatsApp message (free text in-window, approved template otherwise). Mirrors the
doctor-in-the-loop notification pattern in app/modules/urgencies/service.py.
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
    TEMPLATE_LANGUAGE,
    TEMPLATE_RESCHEDULE_NOTICE,
    build_reschedule_notice_params,
)
from app.modules.whatsapp.window import doctor_service_window_open
from app.utils.logger import get_logger

logger = get_logger(__name__)

# Only treat a doctor cancellation as "awaiting reschedule" if it happened
# recently — avoids linking an unrelated old cancellation to a fresh booking.
PENDING_CANCELLATION_LOOKBACK_DAYS = 14


def _format_slot(dt: datetime) -> str:
    """Format an appointment datetime as 'lunes 16/06/2025 a las 16:00' (MX TZ)."""
    dt = dt.astimezone(MX_TIMEZONE) if dt.tzinfo else dt.replace(tzinfo=MX_TIMEZONE)
    return f"{DAYS_ES[dt.weekday()]} {dt.strftime('%d/%m/%Y')} a las {dt.strftime('%H:%M')}"


def _doctor_reschedule_text(patient_name: str, old_slot: str, new_slot: str) -> str:
    """Free-text alert to the doctor (sent while their 24h window is open)."""
    return (
        f"{patient_name} reagendó la cita que cancelaste.\n\n"
        f"Antes: {old_slot}\n"
        f"Ahora: {new_slot}"
    )


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
    cutoff = datetime.now(MX_TIMEZONE) - timedelta(days=PENDING_CANCELLATION_LOOKBACK_DAYS)

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


async def notify_doctor_of_reschedule(
    db: AsyncSession,
    redis_client: aioredis.Redis,
    meta_client,
    new_appointment_id: UUID,
) -> str:
    """Notify the doctor how a freed slot was rescheduled (free text in-window, else template).

    Returns a status: "notified" | "skipped" | "not_found". "not_found" usually
    means the patient turn hasn't committed yet, so the task retries on it.
    """
    new_appointment = await db.get(Appointment, new_appointment_id)
    if not new_appointment:
        return "not_found"
    if not new_appointment.rescheduled_from:
        return "skipped"

    old_appointment = await db.get(Appointment, new_appointment.rescheduled_from)
    office = await db.get(Office, new_appointment.office_id)
    patient = (
        await db.get(Patient, new_appointment.patient_id)
        if new_appointment.patient_id
        else None
    )
    if not office or not patient or not old_appointment:
        return "skipped"
    if not (office.owner_phone and office.whatsapp_phone_id and office.whatsapp_token):
        logger.warning("reschedule_notify_missing_config", office_id=str(office.id))
        return "skipped"

    patient_name = patient.name or "El paciente"
    old_slot = _format_slot(old_appointment.start_datetime)
    new_slot = _format_slot(new_appointment.start_datetime)

    try:
        if await doctor_service_window_open(redis_client, office.id):
            await meta_client.send_text_message(
                phone_number_id=office.whatsapp_phone_id,
                token=office.whatsapp_token,
                to=office.owner_phone,
                text=_doctor_reschedule_text(patient_name, old_slot, new_slot),
            )
            via = "text"
        else:
            await meta_client.send_template_message(
                phone_number_id=office.whatsapp_phone_id,
                token=office.whatsapp_token,
                to=office.owner_phone,
                template_name=TEMPLATE_RESCHEDULE_NOTICE,
                params=build_reschedule_notice_params(patient_name, new_slot),
                language_code=TEMPLATE_LANGUAGE,
            )
            via = "template"
    except Exception as e:
        logger.error(
            "reschedule_notify_doctor_failed",
            new_appointment_id=str(new_appointment_id),
            error=str(e),
            exc_info=True,
        )
        return "skipped"

    logger.info(
        "reschedule_doctor_notified",
        new_appointment_id=str(new_appointment_id),
        via=via,
    )
    return "notified"


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
    if not (office.owner_phone and office.whatsapp_phone_id and office.whatsapp_token):
        logger.warning("abandoned_reschedule_missing_config", office_id=str(office.id))
        return "skipped"

    patient_name = patient.name or "El paciente"
    old_slot = _format_slot(cancelled.start_datetime)

    try:
        if await doctor_service_window_open(redis_client, office.id):
            await meta_client.send_text_message(
                phone_number_id=office.whatsapp_phone_id,
                token=office.whatsapp_token,
                to=office.owner_phone,
                text=_doctor_gave_up_text(patient_name, old_slot),
            )
            via = "text"
        else:
            # Reuses the reschedule_notice template: same shape (patient + slot),
            # and the free-text path carries the nuance when the window is open.
            await meta_client.send_template_message(
                phone_number_id=office.whatsapp_phone_id,
                token=office.whatsapp_token,
                to=office.owner_phone,
                template_name=TEMPLATE_RESCHEDULE_NOTICE,
                params=build_reschedule_notice_params(
                    patient_name, f"canceló en definitiva ({old_slot})"
                ),
                language_code=TEMPLATE_LANGUAGE,
            )
            via = "template"
    except Exception as e:
        logger.error(
            "abandoned_reschedule_notify_failed",
            cancelled_appointment_id=str(cancelled_appointment_id),
            error=str(e),
            exc_info=True,
        )
        return "skipped"

    logger.info(
        "abandoned_reschedule_doctor_notified",
        cancelled_appointment_id=str(cancelled_appointment_id),
        via=via,
    )
    return "notified"
