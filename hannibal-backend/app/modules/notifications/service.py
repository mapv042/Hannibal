"""Configurable doctor notifications: new appointment, cancellation, new patient,
and the daily unconfirmed-appointments summary.

Each notification respects a per-office toggle on Office (notify_*). Sending uses
the shared window-aware helper (app/modules/whatsapp/doctor_notify.py): free text
while the doctor's 24h window is open, approved Meta template otherwise.

Functions return "notified" | "skipped" | "not_found". "not_found" lets the
Celery task retry when the patient turn that triggered the event hasn't committed
yet (the tool handler commits in the conversation manager, after the task is
enqueued).
"""

from __future__ import annotations

from datetime import datetime, time
from uuid import UUID

import redis.asyncio as aioredis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import MX_TIMEZONE
from app.db.models import Appointment, Office, Patient
from app.modules.notifications import templates
from app.modules.reminders.wa_templates import (
    TEMPLATE_DOCTOR_CANCELLATION,
    TEMPLATE_DOCTOR_NEW_APPOINTMENT,
    TEMPLATE_DOCTOR_NEW_PATIENT,
    TEMPLATE_DOCTOR_NEW_PATIENT_APPOINTMENT,
    TEMPLATE_DOCTOR_PATIENT_ARRIVED,
    TEMPLATE_DOCTOR_UNCONFIRMED_SUMMARY,
    build_doctor_cancellation_params,
    build_doctor_new_appointment_params,
    build_doctor_new_patient_appointment_params,
    build_doctor_new_patient_params,
    build_doctor_patient_arrived_params,
    build_doctor_unconfirmed_summary_params,
)
from app.modules.whatsapp.doctor_notify import send_doctor_alert
from app.utils.logger import get_logger

logger = get_logger(__name__)


async def notify_appointment(
    db: AsyncSession,
    redis_client: aioredis.Redis,
    meta_client,
    appointment_id: UUID,
    is_new_patient: bool,
) -> str:
    """Notify the doctor that the bot booked a new appointment.

    When the patient is brand-new and both toggles are on, a single combined
    message is sent. Otherwise each toggle is honored independently.
    """
    appointment = await db.get(Appointment, appointment_id)
    if not appointment:
        return "not_found"

    office = await db.get(Office, appointment.office_id)
    patient = await db.get(Patient, appointment.patient_id)
    if not office or not patient:
        return "skipped"

    tone = office.assistant_tone
    patient_name = patient.name or "El paciente"
    slot = templates.format_slot(appointment.start_datetime)

    want_appointment = office.notify_new_appointment
    want_new_patient = is_new_patient and office.notify_new_patient

    if is_new_patient and want_appointment and office.notify_new_patient:
        text = templates.doctor_new_patient_appointment(patient_name, slot, tone)
        template_name = TEMPLATE_DOCTOR_NEW_PATIENT_APPOINTMENT
        params = build_doctor_new_patient_appointment_params(patient_name, slot)
        log_event = "doctor_new_patient_appointment"
    elif want_appointment:
        text = templates.doctor_new_appointment(patient_name, slot, tone)
        template_name = TEMPLATE_DOCTOR_NEW_APPOINTMENT
        params = build_doctor_new_appointment_params(patient_name, slot)
        log_event = "doctor_new_appointment"
    elif want_new_patient:
        text = templates.doctor_new_patient(patient_name, tone)
        template_name = TEMPLATE_DOCTOR_NEW_PATIENT
        params = build_doctor_new_patient_params(patient_name)
        log_event = "doctor_new_patient"
    else:
        return "skipped"

    return await send_doctor_alert(
        redis_client,
        meta_client,
        office,
        text=text,
        template_name=template_name,
        template_params=params,
        log_event=log_event,
    )


async def notify_cancellation(
    db: AsyncSession,
    redis_client: aioredis.Redis,
    meta_client,
    appointment_id: UUID,
) -> str:
    """Notify the doctor that a patient cancelled their appointment."""
    appointment = await db.get(Appointment, appointment_id)
    if not appointment:
        return "not_found"

    office = await db.get(Office, appointment.office_id)
    patient = await db.get(Patient, appointment.patient_id)
    if not office or not patient:
        return "skipped"
    if not office.notify_cancellation:
        return "skipped"

    patient_name = patient.name or "El paciente"
    slot = templates.format_slot(appointment.start_datetime)

    return await send_doctor_alert(
        redis_client,
        meta_client,
        office,
        text=templates.doctor_cancellation(patient_name, slot, office.assistant_tone),
        template_name=TEMPLATE_DOCTOR_CANCELLATION,
        template_params=build_doctor_cancellation_params(patient_name, slot),
        log_event="doctor_cancellation",
    )


async def _build_patient_brief(
    db: AsyncSession, appointment: Appointment, patient: Patient
) -> list[str]:
    """Short pre-consultation brief: what the doctor needs before walking in.

    Deliberately narrow — the reason for today's visit, when the patient was
    last seen, and the doctor's own internal note. Anything longer stops being
    read, which defeats the point of putting a human at the risk moment.
    """
    lines: list[str] = []

    if appointment.consultation_reason:
        lines.append(f"Motivo: {appointment.consultation_reason}")

    previous = (
        await db.execute(
            select(Appointment)
            .where(
                (Appointment.office_id == appointment.office_id)
                & (Appointment.patient_id == patient.id)
                & (Appointment.id != appointment.id)
                & (Appointment.status == "completed")
            )
            .order_by(Appointment.start_datetime.desc())
            .limit(1)
        )
    ).scalars().first()
    if previous is not None:
        lines.append(f"Última consulta: {templates.format_slot(previous.start_datetime)}")
    else:
        lines.append("Primera consulta con ustedes")

    if patient.internal_notes:
        lines.append(f"Nota: {patient.internal_notes}")

    return lines


async def notify_arrival(
    db: AsyncSession,
    redis_client: aioredis.Redis,
    meta_client,
    appointment_id: UUID,
) -> str:
    """Tell the doctor the patient answered the waiting-room check-in."""
    appointment = await db.get(Appointment, appointment_id)
    if not appointment:
        return "not_found"
    if appointment.arrival_status is None:
        # The report hasn't committed yet — let the task retry.
        return "not_found"

    office = await db.get(Office, appointment.office_id)
    patient = await db.get(Patient, appointment.patient_id)
    if not office or not patient:
        return "skipped"
    if not office.notify_arrival:
        return "skipped"

    patient_name = patient.name or "El paciente"
    brief_lines = await _build_patient_brief(db, appointment, patient)
    detail = templates.arrival_detail(
        appointment.arrival_status, appointment.arrival_eta_minutes
    )

    return await send_doctor_alert(
        redis_client,
        meta_client,
        office,
        text=templates.doctor_patient_arrived(
            patient_name,
            appointment.arrival_status,
            appointment.arrival_eta_minutes,
            brief_lines,
            office.assistant_tone,
        ),
        template_name=TEMPLATE_DOCTOR_PATIENT_ARRIVED,
        template_params=build_doctor_patient_arrived_params(patient_name, detail),
        log_event="doctor_patient_arrived",
    )


async def notify_unconfirmed_summary(
    db: AsyncSession,
    redis_client: aioredis.Redis,
    meta_client,
    office: Office,
) -> str:
    """Send the doctor a digest of today's still-unconfirmed appointments.

    The caller (beat task) decides WHEN to run this and guards idempotency; here
    we just gather today's scheduled (unconfirmed) appointments and send.
    """
    if not office.notify_unconfirmed:
        return "skipped"

    now = datetime.now(MX_TIMEZONE)
    start_of_day = datetime.combine(now.date(), time.min, tzinfo=MX_TIMEZONE)
    end_of_day = datetime.combine(now.date(), time.max, tzinfo=MX_TIMEZONE)

    result = await db.execute(
        select(Appointment)
        .where(
            (Appointment.office_id == office.id)
            & (Appointment.status == "scheduled")
            & (Appointment.start_datetime >= start_of_day)
            & (Appointment.start_datetime <= end_of_day)
        )
        .order_by(Appointment.start_datetime.asc())
    )
    appointments = result.scalars().all()
    if not appointments:
        return "skipped"

    slots = [templates.format_slot(a.start_datetime) for a in appointments]
    text = templates.doctor_unconfirmed_summary(slots, office.assistant_tone)

    return await send_doctor_alert(
        redis_client,
        meta_client,
        office,
        text=text,
        template_name=TEMPLATE_DOCTOR_UNCONFIRMED_SUMMARY,
        template_params=build_doctor_unconfirmed_summary_params(str(len(slots))),
        log_event="doctor_unconfirmed_summary",
    )
