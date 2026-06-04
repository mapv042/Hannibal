"""Celery tasks for reminder sending and follow-up operations."""

from __future__ import annotations

import sys
import traceback
from uuid import UUID, uuid4
from datetime import datetime, timedelta, date
import asyncio

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession
from zoneinfo import ZoneInfo

from celery import shared_task

from app.db.base import get_async_session_maker
from app.db.models import Appointment, Office, Patient, Conversation, Message
from app.modules.reminders.templates import (
    reminder_day_before,
    reminder_4h,
    reminder_1h,
    post_appointment_followup,
    confirmation_request,
)
from app.modules.reminders.wa_templates import (
    TEMPLATE_LANGUAGE,
    TEMPLATE_REMINDER,
    TEMPLATE_CONFIRMATION_DAY_BEFORE,
    TEMPLATE_FOLLOW_UP,
    format_appointment_date,
    format_explicit_date,
    build_reminder_params,
    build_confirmation_params,
    build_follow_up_params,
)
from app.modules.whatsapp.window import service_window_open
from app.utils.logger import get_logger

logger = get_logger(__name__)

MX_TZ = ZoneInfo("America/Mexico_City")

FLAG_MAP = {
    "day_before": "reminder_day_before_sent",
    "4h": "reminder_4h_sent",
    "1h": "reminder_1h_sent",
}

# Free-text builders used while the 24h window is open (one per reminder type).
FREETEXT_REMINDER_MAP = {
    "day_before": reminder_day_before,
    "4h": reminder_4h,
    "1h": reminder_1h,
}


def _log(msg: str):
    """Print to stderr so Railway always captures it."""
    print(f"[CELERY] {msg}", file=sys.stderr, flush=True)


def _log_exception(task_name: str, e: Exception):
    """Log full traceback to stderr."""
    _log(f"{task_name} FAILED: {e}")
    traceback.print_exc(file=sys.stderr)
    sys.stderr.flush()


async def _get_or_create_conversation(
    db: AsyncSession, office_id, whatsapp_id: str, patient_id
) -> Conversation:
    """Find the patient's open conversation for this office, creating one if needed."""
    result = await db.execute(
        select(Conversation).where(
            and_(
                Conversation.office_id == office_id,
                Conversation.whatsapp_id == whatsapp_id,
                Conversation.status != "archived",
            )
        )
    )
    conversation = result.scalar_one_or_none()
    if conversation is None:
        conversation = Conversation(
            id=uuid4(),
            office_id=office_id,
            patient_id=patient_id,
            whatsapp_id=whatsapp_id,
            status="active",
        )
        db.add(conversation)
        await db.flush()
    return conversation


async def _record_outgoing_message(
    db: AsyncSession,
    office: Office,
    patient: Patient,
    *,
    content: str,
    via: str,
    template_name: str,
    whatsapp_message_id: str | None,
) -> None:
    """Persist a bot-sent message so it shows up in the dashboard history.

    Best-effort: a failure here must not roll back the send/idempotency flag,
    so errors are logged and swallowed.
    """
    try:
        conversation = await _get_or_create_conversation(
            db, office.id, patient.whatsapp_id, patient.id
        )
        message = Message(
            id=uuid4(),
            conversation_id=conversation.id,
            content=content,
            type="text",
            direction="outgoing",
            whatsapp_message_id=whatsapp_message_id,
            delivery_status="sent",
            extra_metadata={
                "via": via,
                "template_name": template_name if via == "template" else None,
                "source": "reminder_task",
            },
        )
        db.add(message)
        conversation.last_message_at = datetime.now(MX_TZ)
    except Exception as e:
        _log_exception("record_outgoing_message", e)


async def _send_free_or_template(
    meta_client,
    db: AsyncSession,
    office: Office,
    patient: Patient,
    *,
    free_text: str,
    template_name: str,
    params: list,
) -> str:
    """Send free-form text if the 24h window is open, else an approved template.

    Records the sent message in the conversation history and returns "text" or
    "template" indicating which path was taken.
    """
    if await service_window_open(db, office.id, patient.whatsapp_id):
        message_id = await meta_client.send_text_message(
            phone_number_id=office.whatsapp_phone_id,
            token=office.whatsapp_token,
            to=patient.whatsapp_id,
            text=free_text,
        )
        via = "text"
    else:
        message_id = await meta_client.send_template_message(
            phone_number_id=office.whatsapp_phone_id,
            token=office.whatsapp_token,
            to=patient.whatsapp_id,
            template_name=template_name,
            params=params,
            language_code=TEMPLATE_LANGUAGE,
        )
        via = "template"

    await _record_outgoing_message(
        db,
        office,
        patient,
        content=free_text,
        via=via,
        template_name=template_name,
        whatsapp_message_id=message_id,
    )
    return via


async def _send_reminder(appointment_id: str, reminder_type: str) -> None:
    """
    Shared async logic for all reminder types.

    Loads appointment/patient/office, checks idempotency,
    builds message from template, sends via WhatsApp, marks as sent.

    Uses SELECT FOR UPDATE to prevent race conditions when multiple
    Celery tasks for the same reminder fire simultaneously.
    """
    from app.modules.whatsapp.meta_client import MetaCloudClient

    flag_attr = FLAG_MAP[reminder_type]

    async with get_async_session_maker()() as db:
        # Lock the row to prevent race conditions with duplicate tasks
        result = await db.execute(
            select(Appointment)
            .where(Appointment.id == UUID(appointment_id))
            .with_for_update()
        )
        appointment = result.scalar_one_or_none()
        if not appointment:
            _log(f"send_reminder_{reminder_type}: not found appointment_id={appointment_id}")
            return

        # Idempotency check (safe under FOR UPDATE lock)
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

        # Build both variants: free text (in-window) and template (out-of-window)
        start_local = appointment.start_datetime.astimezone(MX_TZ)
        now_local = datetime.now(MX_TZ)
        appointment_date = format_appointment_date(start_local, now_local)
        appointment_time = start_local.strftime("%H:%M")

        appointment_data = {
            "patient_name": patient.name or "paciente",
            "time": appointment_time,
            "date": appointment_date,
            "office_name": office.name,
            "assistant_name": office.assistant_name,
        }
        free_text = FREETEXT_REMINDER_MAP[reminder_type](
            appointment_data, tone=office.assistant_tone
        )
        params = build_reminder_params(
            patient_name=patient.name or "paciente",
            appointment_date=appointment_date,
            appointment_time=appointment_time,
            location=office.name,
        )

        meta_client = MetaCloudClient()
        via = await _send_free_or_template(
            meta_client,
            db,
            office,
            patient,
            free_text=free_text,
            template_name=TEMPLATE_REMINDER,
            params=params,
        )

        # Mark as sent
        setattr(appointment, flag_attr, True)
        await db.commit()

        _log(f"send_reminder_{reminder_type}: sent via {via} to patient_id={patient.id} appointment_id={appointment_id}")


# --- Celery tasks (thin wrappers) ---


@shared_task(bind=True)
def send_reminder_day_before(self, appointment_id: str):
    """Send day-before reminder."""
    _log(f"send_reminder_day_before: START appointment_id={appointment_id}")
    try:
        asyncio.run(_send_reminder(appointment_id, "day_before"))
        _log(f"send_reminder_day_before: DONE appointment_id={appointment_id}")
    except Exception as e:
        _log_exception("send_reminder_day_before", e)
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
        free_text = post_appointment_followup(
            appointment_data,
            instructions=appointment.instructions,
            tone=office.assistant_tone,
        )
        params = build_follow_up_params(
            patient_name=patient.name or "paciente",
            location=office.name,
        )

        meta_client = MetaCloudClient()
        await _send_free_or_template(
            meta_client,
            db,
            office,
            patient,
            free_text=free_text,
            template_name=TEMPLATE_FOLLOW_UP,
            params=params,
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

                    start_local = appointment.start_datetime.astimezone(MX_TZ)
                    appointment_date = format_explicit_date(start_local)
                    appointment_time = start_local.strftime("%H:%M")

                    appointment_data = {
                        "patient_name": patient.name or "paciente",
                        "time": appointment_time,
                        "date": appointment_date,
                        "office_name": office.name,
                        "assistant_name": office.assistant_name,
                    }
                    free_text = confirmation_request(
                        appointment_data, tone=office.assistant_tone
                    )
                    params = build_confirmation_params(
                        patient_name=patient.name or "paciente",
                        location=office.name,
                        appointment_date=appointment_date,
                        appointment_time=appointment_time,
                    )

                    # Free text within the 24h window, approved template otherwise
                    await _send_free_or_template(
                        meta_client,
                        db,
                        office,
                        patient,
                        free_text=free_text,
                        template_name=TEMPLATE_CONFIRMATION_DAY_BEFORE,
                        params=params,
                    )

                    # Text fed to the AI history so it has context on the reply
                    message = free_text

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

                    # Add confirmation message to claude_history so the AI
                    # has context when the patient replies
                    session.claude_history.append({
                        "role": "assistant",
                        "content": message,
                    })

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
    """Async implementation of reminder reconciliation.

    Per-office reminders are configurable (see ReminderRule). The day-before
    reminder must be scheduled before the appointment day, so we look at a
    multi-day window and (re)schedule any reminder that hasn't been sent yet.
    The Celery tasks are idempotent (guarded by the per-type sent flag), so
    rescheduling an already-pending reminder is harmless.
    """
    from app.modules.reminders.scheduler import schedule_reminders
    from app.modules.reminders.rules import get_active_reminder_rules
    from app.core.constants import SENT_FLAG_BY_REMINDER_TYPE

    # How far ahead to look. Must cover the earliest reminder offset
    # (day_before = 24h before) plus margin.
    LOOKAHEAD_DAYS = 2

    async with get_async_session_maker()() as db:
        try:
            now_mx = datetime.now(MX_TZ)
            today = now_mx.date()
            window_end_date = today + timedelta(days=LOOKAHEAD_DAYS)

            start_of_window = datetime.combine(today, datetime.min.time(), tzinfo=MX_TZ)
            end_of_window = datetime.combine(window_end_date, datetime.max.time(), tzinfo=MX_TZ)

            result = await db.execute(
                select(Appointment).where(
                    and_(
                        Appointment.start_datetime >= start_of_window,
                        Appointment.start_datetime <= end_of_window,
                        Appointment.status.in_(["scheduled", "confirmed"]),
                    )
                )
            )
            appointments = result.scalars().all()

            _log(
                f"reconcile_reminders: {len(appointments)} appointments in "
                f"[{today} .. {window_end_date}]"
            )

            # Cache rules per office to avoid repeated lookups within the run.
            rules_cache: dict = {}

            for appointment in appointments:
                if appointment.office_id not in rules_cache:
                    rules_cache[appointment.office_id] = await get_active_reminder_rules(
                        db, appointment.office_id
                    )
                office_rules = rules_cache[appointment.office_id]

                # Only (re)schedule reminders that haven't been sent yet.
                pending_rules = [
                    (rtype, offset)
                    for rtype, offset in office_rules
                    if not getattr(
                        appointment,
                        SENT_FLAG_BY_REMINDER_TYPE.get(rtype, ""),
                        False,
                    )
                ]

                if pending_rules:
                    schedule_reminders(
                        appointment.id, appointment.start_datetime, pending_rules
                    )

            _log(f"reconcile_reminders: processed {len(appointments)} appointments")

        except Exception as e:
            _log_exception("reconcile_reminders", e)
