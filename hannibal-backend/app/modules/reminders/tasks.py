"""Celery tasks for reminder sending and follow-up operations."""

from __future__ import annotations

import sys
import traceback
from uuid import UUID
from datetime import datetime, timedelta, date
import asyncio

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from celery import shared_task

from app.db.base import get_async_session_maker
from app.db.models import Appointment, Office, Patient
from app.modules.reminders.templates import (
    reminder_48h,
    reminder_24h,
    reminder_2h,
    post_appointment_followup,
    confirmation_request,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)


def _log(msg: str):
    """Print to stderr so Railway always captures it."""
    print(f"[CELERY] {msg}", file=sys.stderr, flush=True)


def _log_exception(task_name: str, e: Exception):
    """Log full traceback to stderr."""
    _log(f"{task_name} FAILED: {e}")
    traceback.print_exc(file=sys.stderr)
    sys.stderr.flush()


@shared_task(bind=True)
def send_reminder_48h(self, appointment_id: str):
    """Send 48-hour reminder to patient."""
    _log(f"send_reminder_48h: START appointment_id={appointment_id}")
    try:
        asyncio.run(_send_reminder_48h_async(appointment_id))
        _log(f"send_reminder_48h: DONE appointment_id={appointment_id}")
    except Exception as e:
        _log_exception("send_reminder_48h", e)
        raise


async def _send_reminder_48h_async(appointment_id: str):
    """Async implementation of 48h reminder."""
    async with get_async_session_maker()() as db:
        appointment = await db.get(Appointment, UUID(appointment_id))
        if not appointment or appointment.reminder_48h_sent:
            _log(f"send_reminder_48h: skipped (not found or already sent) appointment_id={appointment_id}")
            return

        patient = await db.get(Patient, appointment.patient_id)
        office = await db.get(Office, appointment.office_id)

        if not patient or not office:
            _log(f"send_reminder_48h: missing patient/office for appointment_id={appointment_id}")
            return

        appointment_data = {
            "patient_name": patient.name or "paciente",
            "time": appointment.start_time.strftime("%H:%M"),
            "office_name": office.name,
            "assistant_name": office.assistant_name,
        }
        message = reminder_48h(appointment_data, tone=office.assistant_tone)

        # TODO: Send via WhatsApp
        # await whatsapp_service.send_message(patient.whatsapp_id, message)

        appointment.reminder_48h_sent = True
        await db.commit()

        _log(f"send_reminder_48h: sent to patient_id={patient.id}")


@shared_task(bind=True)
def send_reminder_24h(self, appointment_id: str):
    """Send 24-hour reminder to patient."""
    _log(f"send_reminder_24h: START appointment_id={appointment_id}")
    try:
        asyncio.run(_send_reminder_24h_async(appointment_id))
        _log(f"send_reminder_24h: DONE appointment_id={appointment_id}")
    except Exception as e:
        _log_exception("send_reminder_24h", e)
        raise


async def _send_reminder_24h_async(appointment_id: str):
    """Async implementation of 24h reminder."""
    async with get_async_session_maker()() as db:
        appointment = await db.get(Appointment, UUID(appointment_id))
        if not appointment or appointment.reminder_24h_sent:
            _log(f"send_reminder_24h: skipped appointment_id={appointment_id}")
            return

        patient = await db.get(Patient, appointment.patient_id)
        office = await db.get(Office, appointment.office_id)

        if not patient or not office:
            _log(f"send_reminder_24h: missing patient/office for appointment_id={appointment_id}")
            return

        appointment_data = {
            "patient_name": patient.name or "paciente",
            "time": appointment.start_time.strftime("%H:%M"),
            "office_name": office.name,
            "assistant_name": office.assistant_name,
        }
        message = reminder_24h(appointment_data, tone=office.assistant_tone)

        # TODO: Send via WhatsApp
        # await whatsapp_service.send_message(patient.whatsapp_id, message)

        appointment.reminder_24h_sent = True
        await db.commit()

        _log(f"send_reminder_24h: sent to patient_id={patient.id}")


@shared_task(bind=True)
def send_reminder_2h(self, appointment_id: str):
    """Send 2-hour reminder to patient (last minute)."""
    _log(f"send_reminder_2h: START appointment_id={appointment_id}")
    try:
        asyncio.run(_send_reminder_2h_async(appointment_id))
        _log(f"send_reminder_2h: DONE appointment_id={appointment_id}")
    except Exception as e:
        _log_exception("send_reminder_2h", e)
        raise


async def _send_reminder_2h_async(appointment_id: str):
    """Async implementation of 2h reminder."""
    async with get_async_session_maker()() as db:
        appointment = await db.get(Appointment, UUID(appointment_id))
        if not appointment or appointment.reminder_2h_sent:
            _log(f"send_reminder_2h: skipped appointment_id={appointment_id}")
            return

        patient = await db.get(Patient, appointment.patient_id)
        office = await db.get(Office, appointment.office_id)

        if not patient or not office:
            _log(f"send_reminder_2h: missing patient/office for appointment_id={appointment_id}")
            return

        appointment_data = {
            "patient_name": patient.name or "paciente",
            "time": appointment.start_time.strftime("%H:%M"),
            "office_name": office.name,
            "assistant_name": office.assistant_name,
        }
        message = reminder_2h(appointment_data, tone=office.assistant_tone)

        # TODO: Send via WhatsApp
        # await whatsapp_service.send_message(patient.whatsapp_id, message)

        appointment.reminder_2h_sent = True
        await db.commit()

        _log(f"send_reminder_2h: sent to patient_id={patient.id}")


@shared_task(bind=True)
def check_confirmation(self, appointment_id: str):
    """Check if appointment is confirmed 1 hour before."""
    _log(f"check_confirmation: START appointment_id={appointment_id}")
    try:
        asyncio.run(_check_confirmation_async(appointment_id))
        _log(f"check_confirmation: DONE appointment_id={appointment_id}")
    except Exception as e:
        _log_exception("check_confirmation", e)
        raise


async def _check_confirmation_async(appointment_id: str):
    """Async implementation of confirmation check."""
    async with get_async_session_maker()() as db:
        appointment = await db.get(Appointment, UUID(appointment_id))
        if not appointment:
            _log(f"check_confirmation: not found appointment_id={appointment_id}")
            return

        if appointment.status != "confirmed":
            patient = await db.get(Patient, appointment.patient_id)
            office = await db.get(Office, appointment.office_id)

            if not patient or not office:
                _log(f"check_confirmation: missing patient/office for appointment_id={appointment_id}")
                return

            message = (
                f"⏰ {patient.name or 'Estimado(a)'}, tu cita es en 1 hora.\n"
                f"¿Confirmas tu asistencia? 👍"
            )

            # TODO: Send via WhatsApp
            # await whatsapp_service.send_message(patient.whatsapp_id, message)

            _log(f"check_confirmation: urgent reminder sent to patient_id={patient.id}")


@shared_task(bind=True)
def post_follow_up(self, appointment_id: str):
    """Send follow-up message 2 hours after appointment."""
    _log(f"post_follow_up: START appointment_id={appointment_id}")
    try:
        asyncio.run(_post_follow_up_async(appointment_id))
        _log(f"post_follow_up: DONE appointment_id={appointment_id}")
    except Exception as e:
        _log_exception("post_follow_up", e)
        raise


async def _post_follow_up_async(appointment_id: str):
    """Async implementation of post-appointment follow-up."""
    async with get_async_session_maker()() as db:
        appointment = await db.get(Appointment, UUID(appointment_id))
        if not appointment or appointment.follow_up_sent:
            _log(f"post_follow_up: skipped appointment_id={appointment_id}")
            return

        patient = await db.get(Patient, appointment.patient_id)
        office = await db.get(Office, appointment.office_id)

        if not patient or not office:
            _log(f"post_follow_up: missing patient/office for appointment_id={appointment_id}")
            return

        appointment_data = {
            "patient_name": patient.name or "paciente",
            "professional_name": "el profesional",
            "assistant_name": office.assistant_name,
        }
        message = post_appointment_followup(
            appointment_data,
            instructions=appointment.medical_instructions,
            tone=office.assistant_tone,
        )

        # TODO: Send via WhatsApp
        # await whatsapp_service.send_message(patient.whatsapp_id, message)

        appointment.follow_up_sent = True
        await db.commit()

        _log(f"post_follow_up: sent to patient_id={patient.id}")


@shared_task(bind=True)
def send_confirmation_requests(self):
    """
    Daily task to send confirmation requests for tomorrow's appointments.

    Queries all "scheduled" appointments for the next day that haven't had
    a confirmation request sent. For each:
    1. Sends WhatsApp confirmation request message
    2. Sets patient's session status to "waiting_appointment_confirmation"
    3. Marks confirmation_request_sent = True
    """
    _log("send_confirmation_requests: TASK STARTED")
    try:
        asyncio.run(_send_confirmation_requests_async())
        _log("send_confirmation_requests: TASK FINISHED")
    except Exception as e:
        _log_exception("send_confirmation_requests", e)
        raise


async def _send_confirmation_requests_async():
    """Async implementation of day-before confirmation requests."""
    from zoneinfo import ZoneInfo
    from app.modules.whatsapp.meta_client import MetaCloudClient
    from app.modules.conversation.session_store import SessionStore
    from app.modules.conversation.schemas import SessionContext
    from app.db.models import Conversation

    MX_TZ = ZoneInfo("America/Mexico_City")

    async with get_async_session_maker()() as db:
        # Use Mexico City timezone to determine "tomorrow"
        now_mx = datetime.now(MX_TZ)
        tomorrow = (now_mx + timedelta(days=1)).date()

        start_of_tomorrow = datetime.combine(tomorrow, datetime.min.time(), tzinfo=MX_TZ)
        end_of_tomorrow = datetime.combine(tomorrow, datetime.max.time(), tzinfo=MX_TZ)

        # Get all scheduled appointments for tomorrow without confirmation request
        result = await db.execute(
            select(Appointment).where(
                and_(
                    Appointment.start_datetime >= start_of_tomorrow,
                    Appointment.start_datetime <= end_of_tomorrow,
                    Appointment.status == "scheduled",
                    Appointment.confirmation_request_sent == False,
                )
            )
        )
        appointments = result.scalars().all()

        if not appointments:
            _log(f"send_confirmation_requests: no appointments for {tomorrow}")
            return

        _log(f"send_confirmation_requests: {len(appointments)} appointments for {tomorrow}")

        meta_client = MetaCloudClient()
        session_store = SessionStore()

        try:
            for appointment in appointments:
                try:
                    patient = await db.get(Patient, appointment.patient_id)
                    office = await db.get(Office, appointment.office_id)

                    if not patient or not office:
                        _log(f"missing patient/office for appointment_id={appointment.id}")
                        continue

                    if not office.whatsapp_phone_id or not office.whatsapp_token:
                        _log(f"office missing whatsapp config office_id={office.id}")
                        continue

                    if not patient.whatsapp_id:
                        _log(f"patient missing whatsapp_id patient_id={patient.id}")
                        continue

                    # Format date for display
                    day_names = [
                        "lunes", "martes", "miércoles", "jueves",
                        "viernes", "sábado", "domingo",
                    ]
                    formatted_date = (
                        f"{day_names[tomorrow.weekday()]} "
                        f"{tomorrow.strftime('%d/%m/%Y')}"
                    )

                    appointment_data = {
                        "patient_name": patient.name or "paciente",
                        "time": appointment.start_datetime.strftime("%H:%M"),
                        "date": formatted_date,
                        "office_name": office.name,
                        "assistant_name": office.assistant_name,
                    }
                    message = confirmation_request(
                        appointment_data, tone=office.assistant_tone
                    )

                    # Send WhatsApp message
                    await meta_client.send_text_message(
                        phone_number_id=office.whatsapp_phone_id,
                        token=office.whatsapp_token,
                        to=patient.whatsapp_id,
                        text=message,
                    )

                    # Set up session so the patient's reply routes correctly
                    session = await session_store.get_session(
                        patient.whatsapp_id, str(office.id)
                    )
                    if not session:
                        # Find or create a conversation record
                        conv_result = await db.execute(
                            select(Conversation).where(
                                and_(
                                    Conversation.office_id == office.id,
                                    Conversation.whatsapp_id == patient.whatsapp_id,
                                    Conversation.status != "archived",
                                )
                            )
                        )
                        conversation = conv_result.scalar_one_or_none()
                        if not conversation:
                            import uuid as uuid_mod
                            conversation = Conversation(
                                id=uuid_mod.uuid4(),
                                office_id=office.id,
                                whatsapp_id=patient.whatsapp_id,
                                status="active",
                            )
                            db.add(conversation)
                            await db.flush()

                        session = SessionContext(
                            conversation_id=conversation.id,
                            office_id=office.id,
                            whatsapp_id=patient.whatsapp_id,
                            patient_id=patient.id,
                            status="active",
                            claude_history=[],
                            collected_data={},
                        )

                    session.status = "waiting_appointment_confirmation"
                    session.active_appointment_id = appointment.id

                    await session_store.save_session(
                        patient.whatsapp_id, str(office.id), session
                    )

                    # Mark as sent
                    appointment.confirmation_request_sent = True
                    await db.commit()

                    _log(f"confirmation_request DONE for appointment={appointment.id} patient={patient.id}")

                except Exception as e:
                    _log_exception(f"error processing appointment={appointment.id}", e)
                    await db.rollback()
                    continue

        finally:
            await session_store.close()

        _log(f"all confirmation requests completed, total={len(appointments)}")


@shared_task(bind=True)
def notify_waitlist(self, office_id: str, start_time: str):
    """Notify patients in waiting list when a slot opens."""
    _log(f"notify_waitlist: START office_id={office_id}")
    try:
        asyncio.run(_notify_waitlist_async(office_id, start_time))
        _log(f"notify_waitlist: DONE office_id={office_id}")
    except Exception as e:
        _log_exception("notify_waitlist", e)
        raise


async def _notify_waitlist_async(office_id: str, start_time: str):
    """Async implementation of waiting list notification."""
    async with get_async_session_maker()() as db:
        from app.db.models import Waitlist

        result = await db.execute(
            select(Waitlist)
            .where(
                and_(
                    Waitlist.office_id == UUID(office_id),
                    Waitlist.status == "active",
                )
            )
            .order_by(Waitlist.urgent.desc(), Waitlist.created_at)
        )
        waitlist = result.scalars().all()

        if not waitlist:
            _log(f"notify_waitlist: no patients in waitlist for office_id={office_id}")
            return

        patient_entry = waitlist[0]
        patient = await db.get(Patient, patient_entry.patient_id)
        office = await db.get(Office, UUID(office_id))

        if not patient or not office:
            _log(f"notify_waitlist: missing patient/office for office_id={office_id}")
            return

        message = (
            f"¡{patient.name or 'Hola'}! 🎉\n\n"
            f"Se ha liberado un slot disponible en {office.name} para {start_time}.\n\n"
            f"¿Te interesa agendar? Responde con un 👍"
        )

        # TODO: Send via WhatsApp
        # await whatsapp_service.send_message(patient.whatsapp_id, message)

        _log(f"notify_waitlist: notified patient_id={patient.id}")
