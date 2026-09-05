"""Patient-facing notices for appointments changed from the dashboard.

Rule 9 of the self-validation protocol: a cancellation or a reschedule must
never be silent. The WhatsApp flows already cover that — the doctor's assistant
drafts the notice and the doctor approves it — but the dashboard changed the
appointment and told nobody, so a patient could turn up for a cita that had been
cancelled hours earlier.

These notices are deterministic templates, not model-written text, so they don't
go through the draft-and-approve gate: the doctor performed the action in the
dashboard, which is the approval.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Appointment, Office, Patient
from app.modules.reminders.templates import (
    appointment_cancellation,
    appointment_confirmation,
)
from app.modules.reminders.wa_templates import (
    TEMPLATE_LANGUAGE,
    TEMPLATE_OFFICE_MESSAGE,
    build_office_message_params,
)
from app.modules.whatsapp.window import service_window_open
from app.utils.logger import get_logger

logger = get_logger(__name__)


async def _send_patient_notice(
    db: AsyncSession,
    meta_client,
    office: Office,
    patient: Patient,
    text: str,
    log_event: str,
) -> str:
    """Deliver a notice to the patient: free text in-window, template outside.

    Returns "notified" or "skipped". Raises nothing — but unlike the fire-and-
    forget helpers elsewhere, a send failure is re-raised so the calling task
    retries: this is precisely the message Rule 9 says must not go missing.
    """
    if not (office.whatsapp_phone_id and office.whatsapp_token):
        logger.warning(f"{log_event}_missing_config", office_id=str(office.id))
        return "skipped"
    if not patient.whatsapp_id:
        logger.warning(f"{log_event}_patient_without_whatsapp", patient_id=str(patient.id))
        return "skipped"

    if await service_window_open(db, office.id, patient.whatsapp_id):
        await meta_client.send_text_message(
            phone_number_id=office.whatsapp_phone_id,
            token=office.whatsapp_token,
            to=patient.whatsapp_id,
            text=text,
        )
        via = "text"
    else:
        await meta_client.send_template_message(
            phone_number_id=office.whatsapp_phone_id,
            token=office.whatsapp_token,
            to=patient.whatsapp_id,
            template_name=TEMPLATE_OFFICE_MESSAGE,
            params=build_office_message_params(
                patient.name or "paciente", office.name, text
            ),
            language_code=TEMPLATE_LANGUAGE,
        )
        via = "template"

    logger.info(f"{log_event}_notified", office_id=str(office.id), via=via)
    return "notified"


async def _load(db: AsyncSession, appointment_id: UUID):
    """Appointment + office + patient, or None when any is missing."""
    appointment = await db.get(Appointment, appointment_id)
    if appointment is None:
        return None
    office = await db.get(Office, appointment.office_id)
    patient = await db.get(Patient, appointment.patient_id)
    if office is None or patient is None:
        return None
    return appointment, office, patient


async def notify_patient_cancellation(
    db: AsyncSession, meta_client, appointment_id: UUID
) -> str:
    """Tell the patient their appointment was cancelled from the dashboard."""
    loaded = await _load(db, appointment_id)
    if loaded is None:
        return "not_found"
    appointment, office, patient = loaded

    from app.modules.ai.tool_helpers import format_appointment_dt

    text = appointment_cancellation(
        {
            "patient_name": patient.name or "paciente",
            "date": format_appointment_dt(appointment.start_datetime),
            "office_name": office.name,
            "assistant_name": office.assistant_name,
        },
        tone=office.assistant_tone,
    )
    return await _send_patient_notice(
        db, meta_client, office, patient, text, "patient_cancellation"
    )


async def notify_patient_reschedule(
    db: AsyncSession, meta_client, appointment_id: UUID
) -> str:
    """Tell the patient their appointment was moved from the dashboard."""
    loaded = await _load(db, appointment_id)
    if loaded is None:
        return "not_found"
    appointment, office, patient = loaded

    from app.modules.ai.tool_helpers import format_appointment_dt, localize_mx

    local = localize_mx(appointment.start_datetime)
    text = appointment_confirmation(
        {
            "patient_name": patient.name or "paciente",
            "date": format_appointment_dt(appointment.start_datetime),
            "time": local.strftime("%H:%M"),
            "office_name": office.name,
            "assistant_name": office.assistant_name,
        },
        tone=office.assistant_tone,
    )
    # The confirmation template opens with "Confirmamos su cita" — say up front
    # that this is a change, so the patient doesn't read it as a new booking.
    prefix = (
        "Tu cita fue reprogramada."
        if office.assistant_tone == "informal"
        else "Su cita fue reprogramada."
    )
    return await _send_patient_notice(
        db, meta_client, office, patient, f"{prefix}\n\n{text}", "patient_reschedule"
    )


async def alert_doctor_undelivered_notice(
    db: AsyncSession, redis_client, meta_client, appointment_id: UUID, kind: str
) -> str:
    """Last resort: tell the doctor a patient notice could not be delivered.

    Rule 9 says a notice that fails must be retried or escalated — never
    silently dropped. Once the retries are spent, the only honest move is to
    hand the problem to the human who can pick up the phone.
    """
    from app.modules.audit import templates as audit_templates
    from app.modules.reminders.wa_templates import (
        TEMPLATE_DOCTOR_SYNC_WARNING,
        build_doctor_sync_warning_params,
    )
    from app.modules.whatsapp.doctor_notify import send_doctor_alert

    loaded = await _load(db, appointment_id)
    if loaded is None:
        return "skipped"
    appointment, office, patient = loaded

    what = "la cancelación" if kind == "cancellation" else "el cambio de horario"
    detail = f"no pudimos entregarle por WhatsApp el aviso sobre {what}"
    patient_name = patient.name or "un paciente"
    slot = audit_templates.format_slot(appointment.start_datetime)

    return await send_doctor_alert(
        redis_client,
        meta_client,
        office,
        text=(
            f"No pude avisarle a {patient_name} sobre {what} de su cita del {slot}. "
            f"Conviene contactarlo por otro medio."
        ),
        template_name=TEMPLATE_DOCTOR_SYNC_WARNING,
        template_params=build_doctor_sync_warning_params(patient_name, detail),
        log_event="patient_notice_undelivered_alert",
    )
