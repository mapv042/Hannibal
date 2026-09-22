"""Reminder sending, driven by a periodic sweep over due reminders.

Every few minutes `dispatch_due_reminders` asks the database which reminders are
due — from each office's ReminderRule rows and each appointment's start time and
sent flags — and dispatches the matching task. Nothing is scheduled at booking
time, so there is no far-future Celery `eta` to lose on a restart, redeliver
twice, or reconcile nightly.

Each send task is independently idempotent: it re-reads its appointment under
`SELECT FOR UPDATE`, re-checks the sent flag and the status, and only then
sends. A duplicate dispatch is therefore a no-op rather than a duplicate
message.
"""

from __future__ import annotations

from uuid import UUID, uuid4
from datetime import datetime, timedelta

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession
from zoneinfo import ZoneInfo

from celery import shared_task

from app.core.celery_dispatch import dispatch
from app.core.constants import (
    MAX_REMINDER_OFFSET,
    MIN_REMINDER_OFFSET,
    SENT_FLAG_BY_REMINDER_TYPE,
    ReminderType,
)
from app.core.task_runner import run_task
from app.db.base import get_async_session_maker
from app.db.models import Appointment, Office, Patient, Conversation, Message
from app.modules.reminders.scheduler import due_at, is_still_worth_sending
from app.modules.reminders.templates import (
    reminder_week_before,
    reminder_6h,
    arrival_check,
    post_appointment_followup,
    confirmation_request,
    reminder_day_before,
)
from app.modules.reminders.wa_templates import (
    TEMPLATE_LANGUAGE,
    TEMPLATE_REMINDER,
    TEMPLATE_ARRIVAL_CHECK_IN,
    TEMPLATE_CONFIRMATION_DAY_BEFORE,
    TEMPLATE_FOLLOW_UP,
    format_appointment_date,
    format_explicit_date,
    build_arrival_check_params,
    build_reminder_params,
    build_confirmation_params,
    build_follow_up_params,
)
from app.modules.conversation.session_store import SessionStore
from app.modules.whatsapp.window import service_window_open
from app.utils.dates import now_mx
from app.utils.logger import get_logger

logger = get_logger(__name__)

MX_TZ = ZoneInfo("America/Mexico_City")

# Statuses whose reminders are still relevant. "completed" is included for the
# post-appointment follow-up; each task applies its own narrower guard.
SWEEPABLE_STATUSES = ("scheduled", "confirmed", "completed")

# Reminder types handled by the generic `_send_reminder` path: a plain nudge,
# no buttons, no session priming.
FLAG_MAP = {
    ReminderType.WEEK_BEFORE.value: "reminder_week_before_sent",
    ReminderType.SIX_HOURS.value: "reminder_6h_sent",
}

# Free-text builders used while the 24h window is open (one per reminder type).
FREETEXT_REMINDER_MAP = {
    ReminderType.WEEK_BEFORE.value: reminder_week_before,
    ReminderType.SIX_HOURS.value: reminder_6h,
}


def _log(msg: str) -> None:
    logger.info("celery_task", detail=msg)


def _log_exception(task_name: str, e: Exception) -> None:
    logger.error("celery_task_failed", task=task_name, error=str(e), exc_info=True)


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


async def _prime_session_for_appointment(
    session_store,
    db: AsyncSession,
    office: Office,
    patient: Patient,
    appointment: Appointment,
    outgoing_text: str,
    *,
    status: str,
) -> None:
    """Point the patient's session at an appointment we just asked about.

    A tapped button reaches the model as its title text — the button id is
    dropped on the way in — so the appointment being asked about has to travel
    in the session instead. `status` gates which context block the prompt
    builder emits (confirmation vs. arrival).

    The previous thread is closed rather than appended to. The office is opening
    a new topic about a specific appointment, and a half-finished exchange left
    over from before ("¿confirmas estos datos?") competes with it for the
    patient's next word: answering "confirmar" would resume the old booking
    instead of confirming the cita we just asked about. The model can re-read
    anything it needs through its tools; it cannot un-close the wrong cita.
    """
    from app.modules.conversation.schemas import SessionContext

    conversation = await _get_or_create_conversation(
        db, office.id, patient.whatsapp_id, patient.id
    )
    session = SessionContext(
        conversation_id=conversation.id,
        office_id=office.id,
        whatsapp_id=patient.whatsapp_id,
        patient_id=patient.id,
        status=status,
        # The question itself is the whole history, so the reply ("sí", "ya
        # casi") has exactly one thing to attach to.
        claude_history=[{"role": "assistant", "content": outgoing_text}],
        collected_data={},
        active_appointment_id=appointment.id,
    )

    await session_store.save_session(patient.whatsapp_id, str(office.id), session)


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
        conversation.last_message_at = now_mx()
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


async def _load_sendable(
    db: AsyncSession, appointment_id: str, flag_attr: str, task_name: str
) -> tuple[Appointment, Patient, Office] | None:
    """Lock the appointment and check everything needed before sending.

    Returns (appointment, patient, office) when the send should proceed, or None
    when it must be skipped (already sent, cancelled, missing config). The row
    lock makes the flag check safe against a duplicate dispatch.
    """
    result = await db.execute(
        select(Appointment).where(Appointment.id == UUID(appointment_id)).with_for_update()
    )
    appointment = result.scalar_one_or_none()
    if not appointment:
        _log(f"{task_name}: not found appointment_id={appointment_id}")
        return None

    if getattr(appointment, flag_attr):
        _log(f"{task_name}: already sent appointment_id={appointment_id}")
        return None

    if appointment.status not in ("scheduled", "confirmed"):
        _log(f"{task_name}: skipped status={appointment.status} appointment_id={appointment_id}")
        return None

    patient = await db.get(Patient, appointment.patient_id)
    office = await db.get(Office, appointment.office_id)
    if not patient or not office:
        _log(f"{task_name}: missing patient/office appointment_id={appointment_id}")
        return None
    if not office.whatsapp_phone_id or not office.whatsapp_token:
        _log(f"{task_name}: office missing whatsapp config office_id={office.id}")
        return None
    if not patient.whatsapp_id:
        _log(f"{task_name}: patient missing whatsapp_id patient_id={patient.id}")
        return None

    return appointment, patient, office


# --------------------------------------------------------------------------- #
# Send paths
# --------------------------------------------------------------------------- #

async def _send_reminder(appointment_id: str, reminder_type: str) -> None:
    """Plain patient reminder (week before, 6h before): text or template."""
    from app.modules.whatsapp.transport import get_meta_client

    flag_attr = FLAG_MAP[reminder_type]
    task_name = f"send_reminder_{reminder_type}"

    async with get_async_session_maker()() as db:
        loaded = await _load_sendable(db, appointment_id, flag_attr, task_name)
        if loaded is None:
            return
        appointment, patient, office = loaded

        start_local = appointment.start_datetime.astimezone(MX_TZ)
        now_local = now_mx()
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

        via = await _send_free_or_template(
            get_meta_client(),
            db,
            office,
            patient,
            free_text=free_text,
            template_name=TEMPLATE_REMINDER,
            params=params,
        )

        setattr(appointment, flag_attr, True)
        await db.commit()

        _log(f"{task_name}: sent via {via} to patient_id={patient.id} appointment_id={appointment_id}")


async def _send_day_before(appointment_id: str) -> None:
    """Day-before touchpoint: one message that reminds and asks to confirm.

    This used to be two independent mechanisms — the `day_before` reminder rule
    and a separate daily "confirmation requests" beat job — which both fired the
    day before with near-identical text, each with its own sent flag, neither
    aware of the other. The patient got the same thing twice. Now it is one
    message: confirm/cancel buttons for a cita still awaiting confirmation, a
    plain reminder for one the patient already confirmed.
    """
    from app.modules.whatsapp.transport import get_meta_client

    async with get_async_session_maker()() as db:
        loaded = await _load_sendable(
            db, appointment_id, "reminder_day_before_sent", "send_day_before"
        )
        if loaded is None:
            return
        appointment, patient, office = loaded

        start_local = appointment.start_datetime.astimezone(MX_TZ)
        appointment_time = start_local.strftime("%H:%M")
        patient_name = patient.name or "paciente"
        needs_confirmation = appointment.status == "scheduled"

        appointment_data = {
            "patient_name": patient_name,
            "time": appointment_time,
            "date": format_explicit_date(start_local),
            "office_name": office.name,
            "assistant_name": office.assistant_name,
        }

        meta_client = get_meta_client()
        session_store = SessionStore()
        try:
            if not needs_confirmation:
                # Already confirmed: remind, don't ask again.
                free_text = reminder_day_before(
                    appointment_data, tone=office.assistant_tone
                )
                via = await _send_free_or_template(
                    meta_client,
                    db,
                    office,
                    patient,
                    free_text=free_text,
                    template_name=TEMPLATE_REMINDER,
                    params=build_reminder_params(
                        patient_name=patient_name,
                        appointment_date=appointment_data["date"],
                        appointment_time=appointment_time,
                        location=office.name,
                    ),
                )
            else:
                free_text = confirmation_request(
                    appointment_data, tone=office.assistant_tone
                )
                if await service_window_open(db, office.id, patient.whatsapp_id):
                    message_id = await meta_client.send_interactive_buttons(
                        phone_number_id=office.whatsapp_phone_id,
                        token=office.whatsapp_token,
                        to=patient.whatsapp_id,
                        body_text=free_text,
                        buttons=[
                            {"id": f"confirm_{appointment.id}", "title": "Sí, confirmo"},
                            {"id": f"cancel_{appointment.id}", "title": "No podré asistir"},
                        ],
                    )
                    await _record_outgoing_message(
                        db,
                        office,
                        patient,
                        content=free_text,
                        via="interactive",
                        template_name=TEMPLATE_CONFIRMATION_DAY_BEFORE,
                        whatsapp_message_id=message_id,
                    )
                    via = "interactive"
                else:
                    via = await _send_free_or_template(
                        meta_client,
                        db,
                        office,
                        patient,
                        free_text=free_text,
                        template_name=TEMPLATE_CONFIRMATION_DAY_BEFORE,
                        params=build_confirmation_params(
                            patient_name=patient_name,
                            location=office.name,
                            appointment_date=appointment_data["date"],
                            appointment_time=appointment_time,
                        ),
                    )

                await _prime_session_for_appointment(
                    session_store, db, office, patient, appointment, free_text,
                    status="waiting_appointment_confirmation",
                )
        finally:
            await session_store.close()

        appointment.reminder_day_before_sent = True
        await db.commit()

        _log(
            f"send_day_before: sent via {via} (confirmation={needs_confirmation}) "
            f"patient_id={patient.id} appointment_id={appointment_id}"
        )


async def _send_arrival_check(appointment_id: str) -> None:
    """Waiting-room check-in: "¿ya llegaste?" at the appointment's start time.

    Sends interactive buttons in-window and primes the patient's session so
    their reply is read as an arrival report rather than a new scheduling
    request.
    """
    from app.modules.whatsapp.transport import get_meta_client

    async with get_async_session_maker()() as db:
        loaded = await _load_sendable(
            db, appointment_id, "arrival_check_sent", "send_arrival_check"
        )
        if loaded is None:
            return
        appointment, patient, office = loaded

        patient_name = patient.name or "paciente"
        free_text = arrival_check(
            {"patient_name": patient_name, "office_name": office.name},
            tone=office.assistant_tone,
        )

        meta_client = get_meta_client()
        session_store = SessionStore()
        try:
            # In-window: two taps ("Ya llegué" / "Voy en camino"). Out of window
            # buttons aren't delivered at all, so fall back to the template.
            if await service_window_open(db, office.id, patient.whatsapp_id):
                message_id = await meta_client.send_interactive_buttons(
                    phone_number_id=office.whatsapp_phone_id,
                    token=office.whatsapp_token,
                    to=patient.whatsapp_id,
                    body_text=free_text,
                    buttons=[
                        {"id": f"arrived_{appointment.id}", "title": "Ya llegué"},
                        {"id": f"onway_{appointment.id}", "title": "Voy en camino"},
                    ],
                )
                await _record_outgoing_message(
                    db,
                    office,
                    patient,
                    content=free_text,
                    via="interactive",
                    template_name=TEMPLATE_ARRIVAL_CHECK_IN,
                    whatsapp_message_id=message_id,
                )
                via = "interactive"
            else:
                via = await _send_free_or_template(
                    meta_client,
                    db,
                    office,
                    patient,
                    free_text=free_text,
                    template_name=TEMPLATE_ARRIVAL_CHECK_IN,
                    params=build_arrival_check_params(patient_name, office.name),
                )

            await _prime_session_for_appointment(
                session_store, db, office, patient, appointment, free_text,
                status="waiting_arrival_report",
            )
        finally:
            await session_store.close()

        appointment.arrival_check_sent = True
        await db.commit()

        _log(
            f"send_arrival_check: sent via {via} to patient_id={patient.id} "
            f"appointment_id={appointment_id}"
        )


async def _send_doctor_brief(appointment_id: str) -> None:
    """Pre-consultation brief to the doctor, shortly before the appointment.

    Doctor-facing, so it goes through the notifications service (which knows the
    doctor's own 24h window and both doctor-channel numbers) rather than the
    patient send helpers above.
    """
    import redis.asyncio as aioredis

    from app.config import settings
    from app.modules.notifications.service import notify_appointment_brief
    from app.modules.whatsapp.transport import get_meta_client

    redis_client = aioredis.from_url(settings.redis_url, decode_responses=True)
    try:
        async with get_async_session_maker()() as db:
            result = await db.execute(
                select(Appointment)
                .where(Appointment.id == UUID(appointment_id))
                .with_for_update()
            )
            appointment = result.scalar_one_or_none()
            if not appointment:
                _log(f"send_doctor_brief: not found appointment_id={appointment_id}")
                return
            if appointment.doctor_brief_sent:
                _log(f"send_doctor_brief: already sent appointment_id={appointment_id}")
                return

            status = await notify_appointment_brief(
                db, redis_client, get_meta_client(), appointment.id
            )
            if status == "notified":
                appointment.doctor_brief_sent = True
            await db.commit()
            _log(f"send_doctor_brief: {status} appointment_id={appointment_id}")
    finally:
        await redis_client.close()


async def _post_follow_up_async(appointment_id: str) -> None:
    """Post-appointment follow-up, sent after the visit."""
    from app.modules.whatsapp.transport import get_meta_client

    async with get_async_session_maker()() as db:
        # Not _load_sendable: the follow-up is the one reminder that is still
        # valid for a completed appointment.
        result = await db.execute(
            select(Appointment)
            .where(Appointment.id == UUID(appointment_id))
            .with_for_update()
        )
        appointment = result.scalar_one_or_none()
        if not appointment:
            _log(f"post_follow_up: not found appointment_id={appointment_id}")
            return
        if appointment.follow_up_sent:
            _log(f"post_follow_up: already sent appointment_id={appointment_id}")
            return
        # A cancelled or missed appointment gets no "gracias por tu visita"
        if appointment.status not in ("scheduled", "confirmed", "completed"):
            _log(
                f"post_follow_up: skipped status={appointment.status} "
                f"appointment_id={appointment_id}"
            )
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

        await _send_free_or_template(
            get_meta_client(),
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


# --------------------------------------------------------------------------- #
# Celery tasks (thin wrappers)
# --------------------------------------------------------------------------- #

@shared_task(bind=True)
def send_reminder_week_before(self, appointment_id: str):
    """Send week-before reminder."""
    try:
        run_task(_send_reminder(appointment_id, ReminderType.WEEK_BEFORE.value))
    except Exception as e:
        _log_exception("send_reminder_week_before", e)
        raise


@shared_task(bind=True)
def send_reminder_6h(self, appointment_id: str):
    """Send same-day reminder, scheduled 6 hours before the appointment."""
    try:
        run_task(_send_reminder(appointment_id, ReminderType.SIX_HOURS.value))
    except Exception as e:
        _log_exception("send_reminder_6h", e)
        raise


@shared_task(bind=True)
def send_day_before(self, appointment_id: str):
    """Send the day-before reminder / confirmation request."""
    try:
        run_task(_send_day_before(appointment_id))
    except Exception as e:
        _log_exception("send_day_before", e)
        raise


@shared_task(bind=True)
def send_arrival_check(self, appointment_id: str):
    """Ask the patient whether they've arrived, at the appointment's start time."""
    try:
        run_task(_send_arrival_check(appointment_id))
    except Exception as e:
        _log_exception("send_arrival_check", e)
        raise


@shared_task(bind=True)
def send_doctor_brief(self, appointment_id: str):
    """Send the doctor their pre-consultation brief."""
    try:
        run_task(_send_doctor_brief(appointment_id))
    except Exception as e:
        _log_exception("send_doctor_brief", e)
        raise


@shared_task(bind=True)
def post_follow_up(self, appointment_id: str):
    """Send the post-appointment follow-up."""
    try:
        run_task(_post_follow_up_async(appointment_id))
    except Exception as e:
        _log_exception("post_follow_up", e)
        raise


TASK_BY_REMINDER_TYPE = {
    ReminderType.WEEK_BEFORE.value: send_reminder_week_before,
    ReminderType.DAY_BEFORE.value: send_day_before,
    ReminderType.SIX_HOURS.value: send_reminder_6h,
    ReminderType.DOCTOR_BRIEF.value: send_doctor_brief,
    ReminderType.AT_TIME.value: send_arrival_check,
    ReminderType.POST_APPOINTMENT.value: post_follow_up,
}


# --------------------------------------------------------------------------- #
# The sweep (Celery Beat)
# --------------------------------------------------------------------------- #

async def _dispatch_due_reminders_async() -> list[dict]:
    """Dispatch every reminder whose due time has passed and that hasn't been sent.

    Returns:
        One dict per dispatched reminder (appointment_id, reminder_type,
        due_at). The Celery task ignores it; the simulator shows it back to
        the operator so a clock jump reports what it actually caused instead
        of leaving them to guess.
    """
    from app.modules.reminders.rules import get_active_reminder_rules

    now = now_mx()
    # An appointment is in scope if any of its reminders could be due right now:
    # the earliest fires |MIN_REMINDER_OFFSET| before the start, the latest
    # MAX_REMINDER_OFFSET after it. A day of slack on each side absorbs the
    # sending-window clamp.
    window_start = now - timedelta(minutes=MAX_REMINDER_OFFSET) - timedelta(days=1)
    window_end = now + timedelta(minutes=abs(MIN_REMINDER_OFFSET)) + timedelta(days=1)

    async with get_async_session_maker()() as db:
        appointments = (
            await db.execute(
                select(Appointment).where(
                    and_(
                        Appointment.start_datetime >= window_start,
                        Appointment.start_datetime <= window_end,
                        Appointment.status.in_(SWEEPABLE_STATUSES),
                    )
                )
            )
        ).scalars().all()

        rules_cache: dict = {}
        dispatched: list[dict] = []

        for appointment in appointments:
            if appointment.office_id not in rules_cache:
                rules_cache[appointment.office_id] = await get_active_reminder_rules(
                    db, appointment.office_id
                )

            start_local = appointment.start_datetime.astimezone(MX_TZ)

            for reminder_type, offset_minutes in rules_cache[appointment.office_id]:
                task = TASK_BY_REMINDER_TYPE.get(reminder_type)
                flag = SENT_FLAG_BY_REMINDER_TYPE.get(reminder_type)
                if task is None or flag is None:
                    logger.warning(
                        "reminder_unknown_type",
                        appointment_id=str(appointment.id),
                        reminder_type=reminder_type,
                    )
                    continue

                if getattr(appointment, flag, False):
                    continue

                due = due_at(reminder_type, offset_minutes, start_local)
                if due is None or due > now:
                    continue

                if not is_still_worth_sending(
                    reminder_type, offset_minutes, start_local, now
                ):
                    continue

                if dispatch(
                    task,
                    [str(appointment.id)],
                    event="reminder_dispatched",
                    appointment_id=str(appointment.id),
                    reminder_type=reminder_type,
                    due_at=due.isoformat(),
                ):
                    dispatched.append(
                        {
                            "appointment_id": str(appointment.id),
                            "reminder_type": reminder_type,
                            "due_at": due.isoformat(),
                        }
                    )

        _log(
            f"dispatch_due_reminders: {len(dispatched)} dispatched from "
            f"{len(appointments)} appointments in scope"
        )
        return dispatched


@shared_task(bind=True)
def dispatch_due_reminders(self):
    """Beat task: find and dispatch every reminder that has come due."""
    try:
        run_task(_dispatch_due_reminders_async())
    except Exception as e:
        _log_exception("dispatch_due_reminders", e)
        raise
