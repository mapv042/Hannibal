"""One follow-up when a patient goes quiet with a decision in hand.

A conversation is *pending* only when the assistant's last message left the
patient a decision to make: it offered slots to tap (slot_options), or it showed
a booking summary to approve (a draft prepare_booking created in that very
turn) — and the turn booked nothing. Anything else clears it. Every patient turn
recomputes this (schedule_after_turn), so a patient who answered is never
followed up.

A follow-up only goes out the same day the conversation was left pending: a
patient who didn't answer by the next day didn't want to, and a nudge about
yesterday's slots reads as spam. One that can't go out before the sending
window closes (Rule 15) is not armed at all.

When a pending conversation has waited FOLLOW_UP_DELAY, the sweep
(send_due_follow_ups, Celery beat every 15 min) re-checks that nothing has
happened since, re-checks that the slots are still free, and sends ONE fixed
message: the summary to confirm, or the slots that are still free as buttons.
Then it clears the pending state, and the next one may only be armed
FOLLOW_UP_COOLDOWN later — one nudge, never a message every few hours.

"Nothing happened since" is decided without clocks: the conversation's message
count and the patient's active citas are recorded when it is armed. Any new
message — the patient, the doctor from their phone, a reminder, a waitlist
offer — or a cita booked by any channel cancels the follow-up. (Message
timestamps come from the database clock, which the simulator's virtual clock
does not move, so comparing them with now_mx() would lie there.)

The text is code-written, not model-written, like the reminders: nothing to
invent. It goes in the session history so the model knows what the patient is
answering.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.constants import MX_TIMEZONE
from app.db.models import Appointment, Conversation, Message, Office, Patient, UrgencyRequest
from app.modules.ai.tool_helpers import parse_slot_id, resolve_appointment_duration
from app.modules.conversation import slot_options
from app.modules.conversation.session_store import SessionStore
from app.modules.conversation.slot_options import SlotReply
from app.modules.scheduling.availability import check_slot_bookable
from app.modules.whatsapp.coexistence import check_pause, conversation_taken_until
from app.modules.whatsapp.window import SERVICE_WINDOW, last_inbound_at
from app.utils.dates import now_mx
from app.utils.logger import get_logger

logger = get_logger(__name__)

FOLLOW_UP_DELAY = timedelta(hours=2)
# At most one follow-up per conversation in this span, whatever happens.
FOLLOW_UP_COOLDOWN = timedelta(hours=24)
# Free text is refused once the 24h window closes; don't cut it fine.
WINDOW_MARGIN = timedelta(minutes=10)

ACTIVE_STATUSES = ("scheduled", "confirmed")
CONFIRM_BUTTONS = [
    {"id": "follow_up_confirm", "title": "Sí, confirmar"},
    {"id": "follow_up_decline", "title": "No, gracias"},
]

# Redis key of the turn lock (whatsapp/router.CONV_LOCK_KEY): a turn in flight
# settles the follow-up itself, at its end.
_TURN_LOCK_KEY = "conv_lock:{office_id}:{sender}"


# ---------------------------------------------------------------------------
# Arming, at the end of every patient turn
# ---------------------------------------------------------------------------


def pending_kind(reply: SlotReply, ctx) -> Optional[str]:
    """What the patient was left to decide this turn: "draft", "slots" or nothing."""
    if ctx.booked_appointment_ids:
        return None
    draft = ctx.state.draft
    if draft is not None and datetime.fromisoformat(draft.created_at) >= ctx.turn_started_at:
        return "draft"
    if reply.options:
        return "slots"
    return None


async def schedule_after_turn(
    db: AsyncSession,
    office: Office,
    conversation: Conversation,
    reply: SlotReply,
    ctx,
    now: datetime,
) -> None:
    """Arm the follow-up if this turn left a decision pending; otherwise clear it."""
    kind = pending_kind(reply, ctx)
    sent_recently = (
        conversation.follow_up_sent_at is not None
        and now - conversation.follow_up_sent_at < FOLLOW_UP_COOLDOWN
    )
    # Due after today's sending window closes: it could only go out tomorrow.
    too_late_today = next_sending_time(now + FOLLOW_UP_DELAY).date() != now.date()
    if not office.follow_up_enabled or kind is None or sent_recently or too_late_today:
        conversation.follow_up_due_at = None
        conversation.follow_up_context = None
        return

    slot_ids = [s.slot_id for s in reply.options]
    if kind == "draft":
        draft_slot = ctx.state.draft.slot_id
        slot_ids = [draft_slot] + [i for i in slot_ids if i != draft_slot]

    conversation.follow_up_due_at = now + FOLLOW_UP_DELAY
    conversation.follow_up_context = {
        "kind": kind,
        "armed_on": now.date().isoformat(),
        "slot_ids": slot_ids,
        "message_count": await _message_count(db, conversation.id),
        "active_appointment_ids": await _active_appointment_ids(
            db, office.id, conversation.patient_id, now
        ),
    }
    logger.info(
        "follow_up_armed",
        office_id=str(office.id),
        conversation_id=str(conversation.id),
        kind=kind,
        due_at=conversation.follow_up_due_at.isoformat(),
    )


# ---------------------------------------------------------------------------
# The sweep
# ---------------------------------------------------------------------------


async def send_due_follow_ups(
    db: AsyncSession, redis_client, meta_client, now: Optional[datetime] = None
) -> list[dict]:
    """Send (or retire) every follow-up that has come due. One commit per conversation."""
    now = now or now_mx()
    rows = (
        await db.execute(
            select(Conversation, Office)
            .join(Office, Office.id == Conversation.office_id)
            .where(
                Conversation.follow_up_due_at.is_not(None),
                Conversation.follow_up_due_at <= now,
                Office.is_active.is_(True),
            )
            .order_by(Conversation.follow_up_due_at)
        )
    ).all()

    outcomes: list[dict] = []
    for conversation, office in rows:
        # Plain values: a failure rolls back, which expires the loaded rows.
        conversation_id, office_id = conversation.id, office.id
        try:
            outcome = await _follow_up(db, redis_client, meta_client, office, conversation, now)
            await db.commit()
        except Exception as e:
            await db.rollback()
            logger.error(
                "follow_up_failed",
                office_id=str(office_id),
                conversation_id=str(conversation_id),
                error=str(e),
            )
            # Retire it: a row that fails every 15 minutes is noise, and a late
            # nudge is worth less than a repeated error.
            broken = await db.get(Conversation, conversation_id)
            if broken is not None:
                broken.follow_up_due_at = None
                broken.follow_up_context = None
                await db.commit()
            outcome = "error"
        outcomes.append(
            {"conversation_id": str(conversation_id), "office_id": str(office_id), "outcome": outcome}
        )
    return outcomes


async def _follow_up(db, redis_client, meta_client, office, conversation, now) -> str:
    """Send this conversation's follow-up, defer it, or drop it. Returns the outcome."""
    context = conversation.follow_up_context or {}
    whatsapp_id = conversation.whatsapp_id

    def drop(outcome: str) -> str:
        conversation.follow_up_due_at = None
        conversation.follow_up_context = None
        logger.info(
            "follow_up_dropped",
            office_id=str(office.id),
            conversation_id=str(conversation.id),
            outcome=outcome,
        )
        return outcome

    if not office.follow_up_enabled:
        return drop("disabled")
    armed_on = _armed_on(conversation, context)
    if now.date() != armed_on:
        return drop("next_day")
    if await redis_client.exists(_TURN_LOCK_KEY.format(office_id=office.id, sender=whatsapp_id)):
        return "busy"  # the turn in flight re-arms or clears it
    if await _message_count(db, conversation.id) != context.get("message_count"):
        return drop("conversation_moved_on")
    if await check_pause(office.id, redis_client) or await conversation_taken_until(
        office.id, whatsapp_id, redis_client
    ):
        return drop("doctor_handling")

    last_inbound = await last_inbound_at(db, office.id, whatsapp_id)
    if last_inbound is None:
        return drop("no_window")
    window_closes = last_inbound + SERVICE_WINDOW - WINDOW_MARGIN
    if now >= window_closes:
        return drop("window_closed")
    sendable_at = next_sending_time(now)
    if sendable_at > now:
        if sendable_at.date() != armed_on:
            return drop("next_day")
        if sendable_at >= window_closes:
            return drop("window_closed")
        return "deferred"  # stays due; the first sweep once sending opens sends it

    session = await SessionStore(redis_client=redis_client).get_session(whatsapp_id, str(office.id))
    if session is None:
        return drop("no_session")
    patient_id = conversation.patient_id or session.patient_id
    known = set(context.get("active_appointment_ids") or [])
    if set(await _active_appointment_ids(db, office.id, patient_id, now)) - known:
        return drop("booked_elsewhere")
    if await _urgency_pending(db, office.id, whatsapp_id):
        return drop("urgency_pending")

    message = await _compose(db, office, patient_id, session, context, now)
    if message is None:
        return drop("slots_taken")

    message_id = await _send(meta_client, office, whatsapp_id, message)
    db.add(
        Message(
            conversation_id=conversation.id,
            content=message.history_text,
            type="text",
            direction="outgoing",
            whatsapp_message_id=message_id,
            delivery_status="sent",
            extra_metadata={"source": "follow_up", "kind": message.kind},
        )
    )
    # The model must know what the patient is answering.
    session.claude_history.append({"role": "assistant", "content": message.history_text})
    await SessionStore(redis_client=redis_client).save_session(whatsapp_id, str(office.id), session)

    conversation.follow_up_due_at = None
    conversation.follow_up_context = None
    conversation.follow_up_sent_at = now
    logger.info(
        "follow_up_sent",
        office_id=str(office.id),
        conversation_id=str(conversation.id),
        kind=message.kind,
    )
    return "sent"


def _armed_on(conversation, context: dict):
    """The day the conversation was left pending (MX calendar)."""
    if context.get("armed_on"):
        return datetime.fromisoformat(context["armed_on"]).date()
    armed = conversation.follow_up_due_at - FOLLOW_UP_DELAY
    return armed.astimezone(MX_TIMEZONE).date()


def next_sending_time(at: datetime) -> datetime:
    """`at` if it falls in the patient sending window (Rule 15), else when it next opens."""
    opens = at.replace(hour=settings.earliest_reminder_hour, minute=0, second=0, microsecond=0)
    closes = at.replace(hour=settings.latest_reminder_hour, minute=0, second=0, microsecond=0)
    if at < opens:
        return opens
    if at >= closes:
        return opens + timedelta(days=1)
    return at


# ---------------------------------------------------------------------------
# The message
# ---------------------------------------------------------------------------


@dataclass
class FollowUpMessage:
    kind: str  # "draft" (confirm the summary) or "slots"
    history_text: str
    text: str
    slots: Optional[SlotReply] = None


async def _compose(db, office, patient_id, session, context, now) -> Optional[FollowUpMessage]:
    """The follow-up for what was pending, from the slots that are still free; None if none is."""
    formal = office.assistant_tone == "formal"
    hello = await _greeting(db, patient_id)
    duration, _ = await resolve_appointment_duration(db, office, patient_id)

    draft = session.state.draft
    # A pending move: the cita being moved doesn't occupy its new time.
    moving_id = None
    if draft is not None and draft.replaces_appointment_id:
        try:
            moving_id = uuid.UUID(draft.replaces_appointment_id)
        except ValueError:
            moving_id = None

    free: list[str] = []
    for slot_id in context.get("slot_ids") or []:
        start = parse_slot_id(slot_id)
        if isinstance(start, dict) or start <= now:
            continue
        conflict = await check_slot_bookable(
            office.id, start, start + timedelta(minutes=duration), db,
            ignore_appointment_id=moving_id,
        )
        if conflict is None:
            free.append(slot_id)

    if context.get("kind") == "draft" and draft is not None and draft.slot_id in free:
        if draft.replaces_appointment_id:
            what = f"el cambio de {'su' if formal else 'tu'} cita al {draft.label}"
        else:
            what = f"{'su' if formal else 'tu'} cita del {draft.label}"
        text = f"{hello} ¿confirmo {what}?"
        return FollowUpMessage(kind="draft", history_text=text, text=text)

    offered = {s.slot_id: s for s in session.state.offered_slots}
    options = [offered[i] for i in free if i in offered]
    if not options:
        return None
    ask = "¿le aparto" if formal else "¿te aparto"
    which = "este horario? Sigue libre:" if len(options) == 1 else "alguno de estos horarios? Siguen libres:"
    reply = slot_options.offer(f"{hello} {ask} {which}", options)
    return FollowUpMessage(kind="slots", history_text=reply.history_text, text=reply.text, slots=reply)


async def _send(meta_client, office, to: str, message: FollowUpMessage) -> str:
    if message.slots is not None:
        return await slot_options.send_reply(meta_client, office, to, message.slots)
    try:
        return await meta_client.send_interactive_buttons(
            phone_number_id=office.whatsapp_phone_id,
            token=office.whatsapp_token,
            to=to,
            body_text=message.text,
            buttons=CONFIRM_BUTTONS,
        )
    except Exception as e:
        logger.warning("follow_up_buttons_failed", office_id=str(office.id), error=str(e))
        return await meta_client.send_text_message(
            phone_number_id=office.whatsapp_phone_id,
            token=office.whatsapp_token,
            to=to,
            text=message.text,
        )


async def _greeting(db, patient_id) -> str:
    """'Hola Ana,' — first name only, when we know it."""
    patient = await db.get(Patient, patient_id) if patient_id else None
    first = (patient.name or "").split()[0] if patient and patient.name else ""
    return f"Hola {first}," if first else "Hola,"


# ---------------------------------------------------------------------------
# Facts read when arming and when sending
# ---------------------------------------------------------------------------


async def _message_count(db: AsyncSession, conversation_id) -> int:
    return (
        await db.execute(
            select(func.count()).select_from(Message).where(Message.conversation_id == conversation_id)
        )
    ).scalar_one()


async def _active_appointment_ids(db: AsyncSession, office_id, patient_id, now: datetime) -> list[str]:
    """Upcoming active citas of the patient, or booked by them for someone else."""
    if patient_id is None:
        return []
    rows = (
        await db.execute(
            select(Appointment.id).where(
                Appointment.office_id == office_id,
                or_(Appointment.patient_id == patient_id, Appointment.booked_by_patient_id == patient_id),
                Appointment.status.in_(ACTIVE_STATUSES),
                Appointment.start_datetime >= now,
            )
        )
    ).scalars().all()
    return sorted(str(i) for i in rows)


async def _urgency_pending(db: AsyncSession, office_id, whatsapp_id: str) -> bool:
    found = (
        await db.execute(
            select(UrgencyRequest.id).where(
                UrgencyRequest.office_id == office_id,
                UrgencyRequest.patient_whatsapp_id == whatsapp_id,
                UrgencyRequest.status == "pending",
            ).limit(1)
        )
    ).scalar_one_or_none()
    return found is not None
