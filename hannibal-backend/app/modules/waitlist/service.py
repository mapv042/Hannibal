"""Waitlist: offer a freed slot to whoever wanted a sooner one.

Specialists run full agendas; a cancellation used to leave a hole nobody
filled, and the assistant had nothing true to say to "avísame si se libera
algo". Now:

1. The patient tool `join_waitlist` records the wish (a window ending at the
   slot or cita they found too late, a part of the day).
2. A sweep every few minutes (tasks.offer_waitlist_slots) looks for a free
   slot inside each window, oldest entry first, and offers it over WhatsApp,
   holding it for that person for OFFER_HOLD_MINUTES.
3. The answer is settled in code (`settle_answer`): "sí" books through the
   same path as confirm_booking — the offer is the draft, the yes is the
   confirmation — and "no" puts the person back in line without that slot.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any, Optional

import redis.asyncio as aioredis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import MX_TIMEZONE
from app.db.models import Appointment, Conversation, Message, Office, Patient, WaitlistEntry
from app.modules.ai.tool_helpers import (
    CalendarUnavailable,
    format_appointment_dt,
    resolve_appointment_duration,
    slot_id_for,
    slots_on_day,
)
from app.modules.reminders.templates import office_location
from app.utils.dates import now_mx
from app.utils.logger import get_logger
from app.utils.text import plain_yes_no

logger = get_logger(__name__)

OFFER_HOLD_MINUTES = 30
# A slot starting sooner than this can't reasonably be taken from a message.
MIN_LEAD_MINUTES = 120
DEFAULT_WINDOW_DAYS = 14
MAX_ACTIVE_PER_NUMBER = 2

# Session flag while an offer waits for this person's answer.
SESSION_OFFER_KEY = "waitlist_offer"
BUTTON_ACCEPT = "waitlist_accept:"
BUTTON_DECLINE = "waitlist_decline:"

ACTIVE = ("waiting", "offered")


# --------------------------------------------------------------------------- #
# Joining
# --------------------------------------------------------------------------- #


async def join(
    db: AsyncSession,
    office: Office,
    *,
    whatsapp_id: str,
    patient_name: str,
    reason: str,
    window_end: datetime,
    part_of_day: Optional[str] = None,
    replaces_appointment_id: Optional[uuid.UUID] = None,
    intake_notes: Optional[str] = None,
) -> WaitlistEntry | str:
    """Add (or update) a waitlist entry. Returns the entry, or an error message."""
    active = list(
        (
            await db.execute(
                select(WaitlistEntry).where(
                    WaitlistEntry.office_id == office.id,
                    WaitlistEntry.whatsapp_id == whatsapp_id,
                    WaitlistEntry.status.in_(ACTIVE),
                )
            )
        ).scalars().all()
    )
    # The same wish again (same cita to move, or same person) updates it.
    same = next(
        (
            e for e in active
            if (replaces_appointment_id and e.replaces_appointment_id == replaces_appointment_id)
            or (not replaces_appointment_id and not e.replaces_appointment_id
                and e.patient_name.lower() == patient_name.lower())
        ),
        None,
    )
    if same is None and len(active) >= MAX_ACTIVE_PER_NUMBER:
        return "Ya tiene el máximo de solicitudes en lista de espera."

    entry = same or WaitlistEntry(
        id=uuid.uuid4(),
        office_id=office.id,
        whatsapp_id=whatsapp_id,
        created_at=now_mx(),
        status="waiting",
        declined_slots=[],
    )
    entry.patient_name = patient_name
    entry.reason = reason
    entry.intake_notes = intake_notes
    entry.window_end = window_end
    entry.part_of_day = part_of_day
    entry.replaces_appointment_id = replaces_appointment_id
    if same is None:
        db.add(entry)
    await db.flush()
    logger.info("waitlist_joined", office_id=str(office.id), entry_id=str(entry.id))
    return entry


# --------------------------------------------------------------------------- #
# Finding and offering slots
# --------------------------------------------------------------------------- #


async def _duration_for(db: AsyncSession, office: Office, entry: WaitlistEntry) -> int:
    if entry.replaces_appointment_id:
        appointment = await db.get(Appointment, entry.replaces_appointment_id)
        if appointment is not None:
            return appointment.duration_minutes or 30
    patient = (
        await db.execute(
            select(Patient).where(
                Patient.office_id == office.id, Patient.whatsapp_id == entry.whatsapp_id
            ).limit(1)
        )
    ).scalars().first()
    duration, _ = await resolve_appointment_duration(db, office, patient.id if patient else None)
    return duration


async def find_slot(
    db: AsyncSession,
    office: Office,
    entry: WaitlistEntry,
    duration: int,
    taken: set[datetime],
    cache: dict,
) -> Optional[datetime]:
    """The first free slot this entry would take, or None."""
    now = now_mx()
    earliest = now + timedelta(minutes=MIN_LEAD_MINUTES)
    declined = set(entry.declined_slots or [])
    day = now.date()
    last_day = entry.window_end.astimezone(MX_TIMEZONE).date()
    while day <= last_day:
        key = (day, duration)
        if key not in cache:
            try:
                cache[key] = await slots_on_day(office.id, day, db, slot_minutes=duration)
            except CalendarUnavailable:
                return None  # try again next sweep rather than guess
        for slot in cache[key]:
            start = datetime.fromisoformat(slot["slot_id"]).replace(tzinfo=MX_TIMEZONE)
            if start < earliest or start >= entry.window_end:
                continue
            if entry.part_of_day and slot["period"] != entry.part_of_day:
                continue
            if slot["slot_id"] in declined or start in taken:
                continue
            return start
        day += timedelta(days=1)
    return None


def offer_text(office: Office, entry: WaitlistEntry, slot: datetime, moving_from: Optional[str]) -> str:
    formal = office.assistant_tone == "formal"
    label = format_appointment_dt(slot)
    if moving_from:
        ask = (
            f"¿Quiere cambiar su cita del {moving_from} a este horario?"
            if formal
            else f"¿Quieres cambiar tu cita del {moving_from} a este horario?"
        )
    else:
        ask = "¿Lo quiere para su cita?" if formal else "¿Lo quieres para tu cita?"
    hold = (
        f"Se lo apartamos {OFFER_HOLD_MINUTES} minutos."
        if formal
        else f"Te lo apartamos {OFFER_HOLD_MINUTES} minutos."
    )
    return (
        f"Se liberó un horario en {office_location(office)}: {label}. {ask} {hold}"
    )


async def _conversation_for(db: AsyncSession, office: Office, whatsapp_id: str) -> Conversation:
    conversation = (
        await db.execute(
            select(Conversation).where(
                Conversation.office_id == office.id,
                Conversation.whatsapp_id == whatsapp_id,
                Conversation.status != "archived",
            ).limit(1)
        )
    ).scalars().first()
    if conversation is None:
        conversation = Conversation(
            id=uuid.uuid4(), office_id=office.id, whatsapp_id=whatsapp_id, status="active"
        )
        db.add(conversation)
        await db.flush()
    return conversation


async def send_offer(
    db: AsyncSession,
    redis_client: aioredis.Redis,
    meta_client,
    office: Office,
    entry: WaitlistEntry,
    slot: datetime,
) -> None:
    """Offer `slot` to this entry: buttons in-window, the office template outside."""
    from app.modules.conversation.session_store import SessionStore
    from app.modules.conversation.schemas import SessionContext
    from app.modules.reminders.wa_templates import (
        TEMPLATE_LANGUAGE,
        TEMPLATE_OFFICE_MESSAGE,
        build_office_message_params,
    )
    from app.modules.whatsapp.window import service_window_open

    moving_from = None
    if entry.replaces_appointment_id:
        current = await db.get(Appointment, entry.replaces_appointment_id)
        if current is not None:
            moving_from = format_appointment_dt(current.start_datetime)
    text = offer_text(office, entry, slot, moving_from)

    if await service_window_open(db, office.id, entry.whatsapp_id):
        message_id = await meta_client.send_interactive_buttons(
            phone_number_id=office.whatsapp_phone_id,
            token=office.whatsapp_token,
            to=entry.whatsapp_id,
            body_text=text,
            buttons=[
                {"id": f"{BUTTON_ACCEPT}{entry.id}", "title": "Sí, lo quiero"},
                {"id": f"{BUTTON_DECLINE}{entry.id}", "title": "No, gracias"},
            ],
        )
        via = "buttons"
    else:
        message_id = await meta_client.send_template_message(
            phone_number_id=office.whatsapp_phone_id,
            token=office.whatsapp_token,
            to=entry.whatsapp_id,
            template_name=TEMPLATE_OFFICE_MESSAGE,
            params=build_office_message_params(entry.patient_name, office.name, text),
            language_code=TEMPLATE_LANGUAGE,
        )
        via = "template"

    conversation = await _conversation_for(db, office, entry.whatsapp_id)
    db.add(
        Message(
            id=uuid.uuid4(),
            conversation_id=conversation.id,
            content=text,
            type="text",
            direction="outgoing",
            whatsapp_message_id=message_id,
            delivery_status="sent",
            extra_metadata={"source": "waitlist_offer", "via": via},
        )
    )
    conversation.last_message_at = now_mx()

    entry.status = "offered"
    entry.offered_slot = slot
    entry.offered_at = now_mx()

    # The answer may come as a typed "sí" (or after a template, with no
    # buttons): the session remembers which offer it answers.
    store = SessionStore(redis_client=redis_client)
    session = await store.get_session(entry.whatsapp_id, str(office.id))
    if session is None:
        session = SessionContext(
            conversation_id=conversation.id,
            office_id=office.id,
            whatsapp_id=entry.whatsapp_id,
            status="active",
            claude_history=[],
            collected_data={},
        )
    session.collected_data[SESSION_OFFER_KEY] = str(entry.id)
    session.claude_history.append({"role": "assistant", "content": text})
    await store.save_session(entry.whatsapp_id, str(office.id), session)
    logger.info("waitlist_offer_sent", office_id=str(office.id), entry_id=str(entry.id), via=via)


async def sweep_office(
    db: AsyncSession, redis_client: aioredis.Redis, meta_client, office: Office
) -> int:
    """Expire, recycle and offer for one office. Returns offers sent."""
    now = now_mx()
    entries = list(
        (
            await db.execute(
                select(WaitlistEntry)
                .where(WaitlistEntry.office_id == office.id, WaitlistEntry.status.in_(ACTIVE))
                .order_by(WaitlistEntry.created_at)
            )
        ).scalars().all()
    )
    hold = timedelta(minutes=OFFER_HOLD_MINUTES)
    taken = {
        e.offered_slot for e in entries
        if e.status == "offered" and e.offered_at and e.offered_at + hold > now
    }
    cache: dict = {}
    offers = 0
    for entry in entries:
        if entry.window_end <= now + timedelta(minutes=MIN_LEAD_MINUTES):
            entry.status = "expired"
            continue
        if entry.status == "offered":
            if entry.offered_at and entry.offered_at + hold > now:
                continue  # still waiting for this person's answer
            # No answer in time: this slot goes to the next in line.
            _decline_current(entry)
        slot = await find_slot(
            db, office, entry, await _duration_for(db, office, entry), taken, cache
        )
        if slot is None:
            continue
        try:
            await send_offer(db, redis_client, meta_client, office, entry, slot)
        except Exception as e:
            logger.error("waitlist_offer_failed", entry_id=str(entry.id), error=str(e))
            continue
        taken.add(slot)
        offers += 1
    await db.commit()
    return offers


def _decline_current(entry: WaitlistEntry) -> None:
    if entry.offered_slot is not None:
        # As a slot_id (office-local "YYYY-MM-DDTHH:MM"): the DB hands the
        # timestamp back in UTC, and comparing isoformat strings across zones
        # re-offered the very slot the patient had just turned down.
        entry.declined_slots = [*(entry.declined_slots or []), slot_id_for(entry.offered_slot)]
    entry.status = "waiting"
    entry.offered_slot = None
    entry.offered_at = None


# --------------------------------------------------------------------------- #
# The patient's answer
# --------------------------------------------------------------------------- #


def _answer_from(messages: list[dict[str, Any]], text: str, pending: Optional[str]):
    """(entry_id, accepted) from a tapped offer button, or a plain yes/no to a pending offer."""
    for message in messages:
        if message.get("type") != "interactive":
            continue
        button = ((message.get("interactive") or {}).get("button_reply") or {}).get("id", "")
        if button.startswith(BUTTON_ACCEPT):
            return button[len(BUTTON_ACCEPT):], True
        if button.startswith(BUTTON_DECLINE):
            return button[len(BUTTON_DECLINE):], False
    if pending:
        answer = plain_yes_no(text)
        if answer is not None:
            return pending, answer
    return None


async def settle_answer(
    db: AsyncSession,
    office: Office,
    session,
    messages: list[dict[str, Any]],
    text: str,
    redis_client: aioredis.Redis,
) -> Optional[str]:
    """Book or release an offered slot. Returns the fixed reply, or None if not an answer."""
    from app.modules.ai.tools import ToolContext, _execute_booking, _execute_reschedule
    from app.modules.conversation.state import BookingDraft

    pending = session.collected_data.get(SESSION_OFFER_KEY)
    parsed = _answer_from(messages, text, pending)
    if parsed is None:
        return None
    entry_id, accepted = parsed
    session.collected_data.pop(SESSION_OFFER_KEY, None)
    formal = office.assistant_tone == "formal"

    try:
        entry = await db.get(WaitlistEntry, uuid.UUID(entry_id))
    except ValueError:
        entry = None
    if (
        entry is None
        or entry.office_id != office.id
        or entry.whatsapp_id != session.whatsapp_id
        or entry.status != "offered"
    ):
        return (
            "Ese horario ya no está disponible. Sigue en la lista de espera y le avisamos si se libera otro."
            if formal
            else "Ese horario ya no está disponible. Sigues en la lista de espera y te aviso si se libera otro."
        )

    slot = entry.offered_slot
    if not accepted:
        _decline_current(entry)
        return (
            "Entendido. Sigue en la lista de espera; le avisamos si se libera otro horario."
            if formal
            else "Entendido. Sigues en la lista de espera; te aviso si se libera otro horario."
        )

    ctx = ToolContext(
        db=db,
        office=office,
        patient_id=session.patient_id,
        whatsapp_id=session.whatsapp_id,
        redis_client=redis_client,
        state=session.state,
    )
    label = format_appointment_dt(slot)
    if entry.replaces_appointment_id:
        result = await _execute_reschedule(ctx, str(entry.replaces_appointment_id), slot)
    else:
        draft = BookingDraft(
            slot_id=slot.astimezone(MX_TIMEZONE).strftime("%Y-%m-%dT%H:%M"),
            label=label,
            summary=f"Cita para {entry.patient_name}: {label}. Motivo: {entry.reason}.",
            patient_name=entry.patient_name,
            for_self=True,
            reason=entry.reason,
            intake_notes=entry.intake_notes,
            created_at=now_mx().isoformat(),
        )
        result = await _execute_booking(ctx, draft, slot)

    if not result.get("success"):
        logger.warning("waitlist_accept_failed", entry_id=entry_id, error=result.get("error"))
        _decline_current(entry)
        return (
            "Lo siento, ese horario se acaba de ocupar. Sigue en la lista de espera y le avisamos si se libera otro."
            if formal
            else "Lo siento, ese horario se acaba de ocupar. Sigues en la lista de espera y te aviso si se libera otro."
        )

    session.patient_id = ctx.patient_id
    entry.status = "booked"
    entry.appointment_id = uuid.UUID(result.get("appointment_id") or result["new_appointment_id"])
    logger.info("waitlist_booked", office_id=str(office.id), entry_id=entry_id)
    moved = " (la anterior quedó cancelada)" if entry.replaces_appointment_id else ""
    return (
        f"Listo, quedó agendada su cita: {label}, en {office_location(office)}{moved}."
        if formal
        else f"Listo, quedó agendada tu cita: {label}, en {office_location(office)}{moved}."
    )
