"""Celery tasks for reminder sending and follow-up operations."""

from __future__ import annotations

import sys
import traceback
from uuid import UUID
from datetime import datetime, timedelta, date
import asyncio

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession
from zoneinfo import ZoneInfo

from celery import shared_task

from app.db.base import get_async_session_maker
from app.db.models import Appointment, Office, Patient
from app.modules.reminders.templates import (
    reminder_morning,
    reminder_4h,
    reminder_1h,
    reminder_15m,
    post_appointment_followup,
    confirmation_request,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)

MX_TZ = ZoneInfo("America/Mexico_City")

TEMPLATE_MAP = {
    "morning": reminder_morning,
    "4h": reminder_4h,
    "1h": reminder_1h,
    "15m": reminder_15m,
}

FLAG_MAP = {
    "morning": "reminder_morning_sent",
    "4h": "reminder_4h_sent",
    "1h": "reminder_1h_sent",
    "15m": "reminder_15m_sent",
}

DAY_NAMES = [
    "lunes", "martes", "miércoles", "jueves",
    "viernes", "sábado", "domingo",
]


def _log(msg: str):
    """Print to stderr so Railway always captures it."""
    print(f"[CELERY] {msg}", file=sys.stderr, flush=True)


def _log_exception(task_name: str, e: Exception):
    """Log full traceback to stderr."""
    _log(f"{task_name} FAILED: {e}")
    traceback.print_exc(file=sys.stderr)
    sys.stderr.flush()


async def _send_reminder(appointment_id: str, reminder_type: str) -> None:
    """
    Shared async logic for all reminder types.

    Loads appointment/patient/office, checks idempotency,
    builds message from template, sends via WhatsApp, marks as sent.
    """
    from app.modules.whatsapp.meta_client import MetaCloudClient

    flag_attr = FLAG_MAP[reminder_type]
    template_fn = TEMPLATE_MAP[reminder_type]

    async with get_async_session_maker()() as db:
        appointment = await db.get(Appointment, UUID(appointment_id))
        if not appointment:
            _log(f"send_reminder_{reminder_type}: not found appointment_id={appointment_id}")
            return

        # Idempotency check
        if getattr(appointment, flag_attr):
            _log(f"send_reminder_{reminder_type}: already sent appointment_id={appointment_id}")
            return

        # Only send for active appointments
        if appointment.status not in ("scheduled", "confirmed"):
            _log(f"send_reminder_{reminder_type}: skipped status={appointment.status} appointment_id={appointment_id}")
            return

        patient = await db.get(Patient, appointment.patient_id)
        office = await db.get(Office, appointment.office_id)

        if not patient or not office:
            _log(f"send_reminder_{reminder_type}: missing patient/office appointment_id={appointment_id}")
            return

        if not office.whatsapp_phone_id or not office.whatsapp_token:
            _log(f"send_reminder_{reminder_type}: office missing whatsapp config office_id={office.id}")
            return

        if not patient.whatsapp_id:
            _log(f"send_reminder_{reminder_type}: patient missing whatsapp_id patient_id={patient.id}")
            return

        # Build appointment data
        start_local = appointment.start_datetime.astimezone(MX_TZ)
        formatted_date = (
            f"{DAY_NAMES[start_local.weekday()]} "
            f"{start_local.strftime('%d/%m/%Y')}"
        )

        appointment_data = {
            "patient_name": patient.name or "paciente",
            "time": start_local.strftime("%H:%M"),
            "date": formatted_date,
            "office_name": office.name,
            "assistant_name": office.assistant_name,
        }
        message = template_fn(appointment_data, tone=office.assistant_tone)

        # Send via WhatsApp
        meta_client = MetaCloudClient()
        await meta_client.send_text_message(
            phone_number_id=office.whatsapp_phone_id,
            token=office.whatsapp_token,
            to=patient.whatsapp_id,
            text=message,
        )

        # Mark as sent
        setattr(appointment, flag_attr, True)
        await db.commit()

        _log(f"send_reminder_{reminder_type}: sent to patient_id={patient.id} appointment_id={appointment_id}")


# --- Celery tasks (thin wrappers) ---


@shared_task(bind=True)
def send_reminder_morning(self, appointment_id: str):
    """Send morning-of-appointment reminder (8 AM)."""
    _log(f"send_reminder_morning: START appointment_id={appointment_id}")
    try:
        asyncio.run(_send_reminder(appointment_id, "morning"))
        _log(f"send_reminder_morning: DONE appointment_id={appointment_id}")
    except Exception as e:
        _log_exception("send_reminder_morning", e)
        raise


@shared_task(bind=True)
def send_reminder_4h(self, appointment_id: str):
    """Send 4-hour-before reminder."""
    _log(f"send_reminder_4h: START appointment_id={appointment_id}")
    try:
        asyncio.run(_send_reminder(appointment_id, "4h"))
        _log(f"send_reminder_4h: DONE appointment_id={appointment_id}")
    except Exception as e:
        _log_exception("send_reminder_4h", e)
        raise


@shared_task(bind=True)
def send_reminder_1h(self, appointment_id: str):
    """Send 1-hour-before reminder."""
    _log(f"send_reminder_1h: START appointment_id={appointment_id}")
    try:
        asyncio.run(_send_reminder(appointment_id, "1h"))
        _log(f"send_reminder_1h: DONE appointment_id={appointment_id}")
    except Exception as e:
        _log_exception("send_reminder_1h", e)
        raise


@shared_task(bind=True)
def send_reminder_15m(self, appointment_id: str):
    """Send 15-minute-before reminder."""
    _log(f"send_reminder_15m: START appointment_id={appointment_id}")
    try:
        asyncio.run(_send_reminder(appointment_id, "15m"))
        _log(f"send_reminder_15m: DONE appointment_id={appointment_id}")
    except Exception as e:
        _log_exception("send_reminder_15m", e)
        raise


# --- Existing tasks (kept) ---


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
    from app.modules.whatsapp.meta_client import MetaCloudClient

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

        if not office.whatsapp_phone_id or not office.whatsapp_token or not patient.whatsapp_id:
            _log(f"post_follow_up: missing whatsapp config appointment_id={appointment_id}")
            return

        appointment_data = {
            "patient_name": patient.name or "paciente",
            "professional_name": "el profesional",
            "assistant_name": office.assistant_name,
        }
        message = post_appointment_followup(
            appointment_data,
            instructions=appointment.instructions,
            tone=office.assistant_tone,
        )

        meta_client = MetaCloudClient()
        await meta_client.send_text_message(
            phone_number_id=office.whatsapp_phone_id,
            token=office.whatsapp_token,
            to=patient.whatsapp_id,
            text=message,
        )

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
    from app.modules.whatsapp.meta_client import MetaCloudClient
    from app.modules.conversation.session_store import SessionStore
    from app.modules.conversation.schemas import SessionContext
    from app.db.models import Conversation

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
                    formatted_date = (
                        f"{DAY_NAMES[tomorrow.weekday()]} "
                        f"{tomorrow.strftime('%d/%m/%Y')}"
                    )

                    appointment_data = {
                        "patient_name": patient.name or "paciente",
                        "time": appointment.start_datetime.astimezone(MX_TZ).strftime("%H:%M"),
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
    from app.modules.whatsapp.meta_client import MetaCloudClient

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

        if not office.whatsapp_phone_id or not office.whatsapp_token or not patient.whatsapp_id:
            _log(f"notify_waitlist: missing whatsapp config office_id={office_id}")
            return

        message = (
            f"¡{patient.name or 'Hola'}! 🎉\n\n"
            f"Se ha liberado un horario disponible en {office.name} para {start_time}.\n\n"
            f"¿Te interesa agendar? Responde con un 👍"
        )

        meta_client = MetaCloudClient()
        await meta_client.send_text_message(
            phone_number_id=office.whatsapp_phone_id,
            token=office.whatsapp_token,
            to=patient.whatsapp_id,
            text=message,
        )

        _log(f"notify_waitlist: notified patient_id={patient.id}")


@shared_task(bind=True)
def reconcile_reminders(self):
    """
    Daily safety net task (runs at 7 AM).

    Finds today's appointments with missing reminders and re-schedules them.
    """
    _log("reconcile_reminders: TASK STARTED")
    try:
        asyncio.run(_reconcile_reminders_async())
        _log("reconcile_reminders: TASK FINISHED")
    except Exception as e:
        _log_exception("reconcile_reminders", e)
        raise


async def _reconcile_reminders_async():
    """Async implementation of reminder reconciliation."""
    from app.modules.reminders.scheduler import schedule_reminders

    async with get_async_session_maker()() as db:
        try:
            now_mx = datetime.now(MX_TZ)
            today = now_mx.date()

            start_of_today = datetime.combine(today, datetime.min.time(), tzinfo=MX_TZ)
            end_of_today = datetime.combine(today, datetime.max.time(), tzinfo=MX_TZ)

            # Get all active appointments for today
            result = await db.execute(
                select(Appointment).where(
                    and_(
                        Appointment.start_datetime >= start_of_today,
                        Appointment.start_datetime <= end_of_today,
                        Appointment.status.in_(["scheduled", "confirmed"]),
                    )
                )
            )
            appointments = result.scalars().all()

            _log(f"reconcile_reminders: {len(appointments)} appointments for {today}")

            for appointment in appointments:
                # Check if any reminders are still missing
                if (
                    not appointment.reminder_morning_sent
                    or not appointment.reminder_4h_sent
                    or not appointment.reminder_1h_sent
                    or not appointment.reminder_15m_sent
                ):
                    _log(
                        f"reconcile_reminders: missing reminders for appointment_id={appointment.id} "
                        f"morning={appointment.reminder_morning_sent} "
                        f"4h={appointment.reminder_4h_sent} "
                        f"1h={appointment.reminder_1h_sent} "
                        f"15m={appointment.reminder_15m_sent}"
                    )
                    schedule_reminders(appointment.id, appointment.start_datetime)

            _log(f"reconcile_reminders: processed {len(appointments)} appointments")

        except Exception as e:
            _log_exception("reconcile_reminders", e)
