"""Service layer for urgent-appointment requests (doctor-in-the-loop)."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Optional
from uuid import UUID

import redis.asyncio as aioredis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import (
    GCAL_COLOR_URGENT,
    MX_TIMEZONE,
    UrgencyStatus,
)
from app.db.models import (
    Appointment,
    Conversation,
    Message,
    Office,
    Patient,
    UrgencyRequest,
)
from app.modules.google_calendar.service import create_calendar_event
from app.modules.scheduling.availability import get_upcoming_slots
from app.modules.whatsapp.window import (
    doctor_service_window_open,
    service_window_open,
)
from app.modules.reminders.wa_templates import (
    TEMPLATE_LANGUAGE,
    TEMPLATE_OFFICE_MESSAGE,
    TEMPLATE_URGENCY_ALERT,
    build_office_message_params,
    build_urgency_alert_params,
)
from app.modules.urgencies import templates
from app.utils.logger import get_logger
from app.utils.phone import display_or_raw

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Request lifecycle
# ---------------------------------------------------------------------------

async def create_urgency_request(
    db: AsyncSession,
    office_id: UUID,
    patient_id: UUID,
    patient_whatsapp_id: str,
    reason: str,
    preferred_time: Optional[datetime],
) -> UrgencyRequest:
    """Persist a pending urgency request. Caller enqueues notify + timeout tasks."""
    request = UrgencyRequest(
        id=uuid.uuid4(),
        office_id=office_id,
        patient_id=patient_id,
        patient_whatsapp_id=patient_whatsapp_id,
        reason=reason,
        preferred_time=preferred_time,
        status=UrgencyStatus.PENDING.value,
    )
    db.add(request)
    await db.flush()
    logger.info("urgency_request_created", request_id=str(request.id), office_id=str(office_id))
    return request


async def get_pending_urgencies(office_id: UUID, db: AsyncSession) -> list[dict]:
    """Pending requests for an office, shaped for the doctor system prompt."""
    stmt = (
        select(UrgencyRequest, Patient.name)
        .join(Patient, UrgencyRequest.patient_id == Patient.id)
        .where(
            (UrgencyRequest.office_id == office_id)
            & (UrgencyRequest.status == UrgencyStatus.PENDING.value)
        )
        .order_by(UrgencyRequest.created_at)
    )
    rows = (await db.execute(stmt)).all()
    return [
        {
            "id": str(req.id),
            "patient_name": patient_name or "Paciente",
            "reason": req.reason,
            "preferred": templates.format_preferred(req.preferred_time),
        }
        for req, patient_name in rows
    ]


async def resolve_urgency_request(
    db: AsyncSession,
    office: Office,
    meta_client,
    request_id: UUID,
    approved: bool,
    start_dt: Optional[datetime] = None,
    note: Optional[str] = None,
) -> dict:
    """Approve (and book, overbooking allowed) or reject an urgent request.

    On either outcome the patient is notified here so the guarantee does not
    depend on the LLM chaining a second tool. Returns a result dict for the
    doctor tool handler (with `next_step` per CONVENTIONS).
    """
    request = await db.get(UrgencyRequest, request_id)
    if not request or request.office_id != office.id:
        return {"error": "No se encontró la solicitud de urgencia."}
    if request.status != UrgencyStatus.PENDING.value:
        return {
            "error": (
                f"Esa solicitud ya no está pendiente (estado actual: {request.status}). "
                "No se puede volver a resolver."
            )
        }

    patient = await db.get(Patient, request.patient_id)
    if not patient:
        return {"error": "No se encontró al paciente de la solicitud."}

    # --- Rejection ---------------------------------------------------------
    if not approved:
        request.status = UrgencyStatus.REJECTED.value
        request.resolution_note = note
        request.resolved_at = datetime.now(MX_TIMEZONE)
        await db.flush()
        await _send_patient_text(
            db, office, patient, templates.patient_urgency_rejected(office.assistant_tone), meta_client
        )
        logger.info("urgency_request_rejected", request_id=str(request_id))
        return {
            "success": True,
            "decision": "rejected",
            "patient_name": patient.name,
            "next_step": "Ya le avisé al paciente que la urgencia no procede; confírmale al doctor.",
        }

    # --- Approval ----------------------------------------------------------
    if start_dt is None:
        return {"error": "Para aprobar la urgencia necesito la fecha y la hora. Pregúntaselas al doctor."}

    appointment = await _create_urgent_appointment(db, office, patient, start_dt, request.reason)

    # Urgent bookings skip slot validation (overbooking is the point), but they
    # still get the office's reminders.
    from app.modules.reminders.scheduler import schedule_reminders_for_appointment
    await schedule_reminders_for_appointment(db, office.id, appointment.id, start_dt)

    request.status = UrgencyStatus.APPROVED.value
    request.appointment_id = appointment.id
    request.resolution_note = note
    request.resolved_at = datetime.now(MX_TIMEZONE)
    await db.flush()

    local_start = start_dt.astimezone(MX_TIMEZONE) if start_dt.tzinfo else start_dt.replace(tzinfo=MX_TIMEZONE)
    formatted = templates.format_datetime(local_start)
    await _send_patient_text(
        db,
        office,
        patient,
        templates.patient_urgency_approved(formatted, office.name, office.address, office.assistant_tone),
        meta_client,
    )
    logger.info("urgency_request_approved", request_id=str(request_id), appointment_id=str(appointment.id))
    return {
        "success": True,
        "decision": "approved",
        "patient_name": patient.name,
        "appointment_id": str(appointment.id),
        "formatted": formatted,
        "next_step": "La cita urgente quedó agendada y ya le avisé al paciente; confírmaselo al doctor.",
    }


async def expire_urgency_request(
    db: AsyncSession,
    redis_client: aioredis.Redis,
    meta_client,
    request_id: UUID,
) -> None:
    """Timeout fallback: if still pending, mark expired and offer normal slots."""
    request = await db.get(UrgencyRequest, request_id)
    if not request or request.status != UrgencyStatus.PENDING.value:
        return  # Already approved/rejected — nothing to do.

    office = await db.get(Office, request.office_id)
    patient = await db.get(Patient, request.patient_id)

    request.status = UrgencyStatus.EXPIRED.value
    request.resolved_at = datetime.now(MX_TIMEZONE)
    await db.flush()

    if not office or not patient:
        return

    slots_text = ""
    try:
        slots = await get_upcoming_slots(office.id, 7, db, redis_client)
        if slots:
            slots_text = templates.format_slots_list(slots[:3])
    except Exception as e:
        logger.warning("urgency_timeout_slots_failed", request_id=str(request_id), error=str(e))

    await _send_patient_text(
        db,
        office,
        patient,
        templates.patient_urgency_timeout(slots_text, office.assistant_tone),
        meta_client,
    )
    logger.info("urgency_request_expired", request_id=str(request_id))


async def notify_doctor_of_urgency(
    db: AsyncSession,
    redis_client: aioredis.Redis,
    meta_client,
    request_id: UUID,
) -> str:
    """Notify the doctor of a pending urgency (free text in-window, else template).

    Returns a status: "notified" | "skipped" | "not_found". "not_found" usually
    means the patient turn hasn't committed yet, so the task retries on it.
    """
    request = await db.get(UrgencyRequest, request_id)
    if not request:
        return "not_found"
    if request.status != UrgencyStatus.PENDING.value:
        return "skipped"

    office = await db.get(Office, request.office_id)
    patient = await db.get(Patient, request.patient_id)
    if not office or not patient:
        return "skipped"
    if not (office.owner_phone and office.whatsapp_phone_id and office.whatsapp_token):
        logger.warning("urgency_notify_missing_config", office_id=str(request.office_id))
        return "skipped"

    patient_name = patient.name or "Paciente"
    try:
        if await doctor_service_window_open(redis_client, office.id):
            text = templates.doctor_urgency_notification(
                patient_name, request.reason, templates.format_preferred(request.preferred_time)
            )
            await meta_client.send_text_message(
                phone_number_id=office.whatsapp_phone_id,
                token=office.whatsapp_token,
                to=office.owner_phone,
                text=text,
            )
            request.doctor_notified_via = "text"
        else:
            await meta_client.send_template_message(
                phone_number_id=office.whatsapp_phone_id,
                token=office.whatsapp_token,
                to=office.owner_phone,
                template_name=TEMPLATE_URGENCY_ALERT,
                params=build_urgency_alert_params(patient_name),
                language_code=TEMPLATE_LANGUAGE,
            )
            request.doctor_notified_via = "template"
    except Exception as e:
        logger.error("urgency_notify_doctor_failed", request_id=str(request_id), error=str(e), exc_info=True)
        return "skipped"

    await db.flush()
    logger.info(
        "urgency_doctor_notified",
        request_id=str(request_id),
        via=request.doctor_notified_via,
    )
    return "notified"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

async def _create_urgent_appointment(
    db: AsyncSession,
    office: Office,
    patient: Patient,
    start_dt: datetime,
    reason: str,
) -> Appointment:
    """Create the urgent appointment directly (no availability gate = overbook)."""
    existing = await db.execute(
        select(Appointment).where(
            (Appointment.office_id == office.id)
            & (Appointment.patient_id == patient.id)
            & (Appointment.status.in_(["completed", "confirmed", "scheduled"]))
        ).limit(1)
    )
    is_returning = existing.scalars().first() is not None
    duration_min = (
        office.returning_patient_duration_min if is_returning
        else office.new_patient_duration_min
    )
    end_dt = start_dt + timedelta(minutes=duration_min)

    google_event_id = None
    if office.google_calendar_token:
        try:
            google_event_id = await create_calendar_event(
                office_id=office.id,
                title=f"URGENCIA: {patient.name}",
                start_time=start_dt,
                end_time=end_dt,
                description=(
                    f"Motivo: {reason}\n"
                    + (f"Teléfono: {display_or_raw(patient.phone)}\n" if patient.phone else "")
                    + "Cita urgente aprobada por el doctor"
                ),
                db=db,
                color_id=GCAL_COLOR_URGENT,
            )
        except Exception as e:
            logger.error("urgency_create_gcal_failed", error=str(e))

    appointment = Appointment(
        id=uuid.uuid4(),
        office_id=office.id,
        patient_id=patient.id,
        start_datetime=start_dt,
        end_datetime=end_dt,
        duration_minutes=duration_min,
        type="urgent",
        consultation_reason=reason,
        status="scheduled",
        google_event_id=google_event_id,
    )
    db.add(appointment)
    await db.flush()
    return appointment


async def _get_or_create_conversation(
    db: AsyncSession, office_id: UUID, whatsapp_id: str, patient_id: UUID
) -> Conversation:
    result = await db.execute(
        select(Conversation).where(
            (Conversation.office_id == office_id)
            & (Conversation.whatsapp_id == whatsapp_id)
            & (Conversation.status != "archived")
        )
    )
    conversation = result.scalar_one_or_none()
    if conversation is None:
        conversation = Conversation(
            id=uuid.uuid4(),
            office_id=office_id,
            patient_id=patient_id,
            whatsapp_id=whatsapp_id,
            status="active",
        )
        db.add(conversation)
        await db.flush()
    return conversation


async def _send_patient_text(
    db: AsyncSession,
    office: Office,
    patient: Patient,
    text: str,
    meta_client,
) -> str:
    """Send a system message to the patient, window-aware, and record it.

    Free text while the 24h window is open, otherwise the approved
    office_message template. Returns "text" | "template" | "skipped" | "failed".
    """
    if not patient.whatsapp_id:
        return "skipped"
    try:
        if await service_window_open(db, office.id, patient.whatsapp_id):
            wa_message_id = await meta_client.send_text_message(
                phone_number_id=office.whatsapp_phone_id,
                token=office.whatsapp_token,
                to=patient.whatsapp_id,
                text=text,
            )
            via = "text"
        else:
            wa_message_id = await meta_client.send_template_message(
                phone_number_id=office.whatsapp_phone_id,
                token=office.whatsapp_token,
                to=patient.whatsapp_id,
                template_name=TEMPLATE_OFFICE_MESSAGE,
                params=build_office_message_params(
                    patient_name=patient.name or "paciente",
                    location=office.name,
                    text=text,
                ),
                language_code=TEMPLATE_LANGUAGE,
            )
            via = "template"
    except Exception as e:
        logger.error("urgency_patient_send_failed", patient_id=str(patient.id), error=str(e), exc_info=True)
        return "failed"

    try:
        conversation = await _get_or_create_conversation(
            db, office.id, patient.whatsapp_id, patient.id
        )
        db.add(Message(
            id=uuid.uuid4(),
            conversation_id=conversation.id,
            content=text,
            type="text",
            direction="outgoing",
            whatsapp_message_id=wa_message_id,
            delivery_status="sent",
            extra_metadata={"via": via, "source": "urgency"},
        ))
        await db.flush()
    except Exception as e:
        logger.warning("urgency_record_message_failed", error=str(e))
    return via
