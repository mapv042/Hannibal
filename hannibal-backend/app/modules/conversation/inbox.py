"""Read-only view of the WhatsApp threads for the doctor's dashboard.

A doctor will not hand their patients to an assistant they cannot supervise:
this is where they read what it said. Nothing here writes — replying, pausing
or taking over happens over WhatsApp.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.db.models import Conversation, Message, Patient

PREVIEW_CHARS = 120
_NEVER = datetime.min.replace(tzinfo=timezone.utc)


class ConversationSummary(BaseModel):
    id: UUID
    whatsapp_id: str
    patient_id: Optional[UUID] = None
    patient_name: Optional[str] = None
    last_message_at: Optional[datetime] = None
    last_message_preview: Optional[str] = None
    last_message_direction: Optional[str] = None
    # Set while the doctor is handling this patient personally (the assistant
    # is not answering this thread); when it lapses the assistant resumes.
    taken_over_until: Optional[datetime] = None


class InboxMessage(BaseModel):
    id: UUID
    content: str
    direction: str
    # assistant | doctor | doctor_app | reminder | system | patient — who
    # produced the text, so the doctor can tell the bot's words from their own
    # (approved drafts, or typed in their WhatsApp app) and from fixed ones.
    author: str
    delivery_status: Optional[str] = None
    created_at: datetime


def message_author(message: Message) -> str:
    """Who wrote a message, from its direction and the metadata its writer left."""
    if message.direction == "incoming":
        return "patient"
    source = (message.extra_metadata or {}).get("source")
    if source == "doctor_send_message":
        return "doctor"
    if source == "doctor_app":
        return "doctor_app"
    if source == "reminder_task":
        return "reminder"
    if source in ("privacy_consent", "waitlist_offer"):
        return "system"
    return "assistant"


async def _patients_for(
    db: AsyncSession, office_id: UUID, conversations: list[Conversation]
) -> dict[UUID, Patient]:
    """The patient behind each conversation.

    Conversation.patient_id is often empty (the patient flow creates the thread
    before anyone is registered), and a number can belong to several patients
    (a parent who booked for a child). Prefer the linked patient; otherwise the
    earliest patient registered with that WhatsApp id — the person writing.
    """
    linked_ids = {c.patient_id for c in conversations if c.patient_id}
    wa_ids = {c.whatsapp_id for c in conversations if not c.patient_id}
    if not linked_ids and not wa_ids:
        return {}

    rows = (
        await db.execute(
            select(Patient)
            .where(
                Patient.office_id == office_id,
                or_(Patient.id.in_(linked_ids), Patient.whatsapp_id.in_(wa_ids)),
            )
            .order_by(Patient.created_at)
        )
    ).scalars().all()
    by_id = {p.id: p for p in rows}
    by_wa: dict[str, Patient] = {}
    for p in rows:
        by_wa.setdefault(p.whatsapp_id, p)

    resolved: dict[UUID, Patient] = {}
    for c in conversations:
        patient = by_id.get(c.patient_id) if c.patient_id else by_wa.get(c.whatsapp_id)
        if patient is not None:
            resolved[c.id] = patient
    return resolved


async def list_conversations(
    db: AsyncSession,
    office_id: UUID,
    search: Optional[str] = None,
    limit: int = 50,
    redis_client=None,
) -> list[ConversationSummary]:
    """Threads of an office, most recent activity first."""
    query = select(Conversation).where(Conversation.office_id == office_id)

    term = (search or "").strip()
    if term:
        like = f"%{term}%"
        matches = (
            await db.execute(
                select(Patient.id, Patient.whatsapp_id).where(
                    Patient.office_id == office_id,
                    or_(Patient.name.ilike(like), Patient.phone.ilike(like)),
                )
            )
        ).all()
        query = query.where(
            or_(
                Conversation.whatsapp_id.ilike(like),
                Conversation.patient_id.in_([m.id for m in matches]),
                Conversation.whatsapp_id.in_([m.whatsapp_id for m in matches]),
            )
        )

    activity = func.coalesce(Conversation.last_message_at, Conversation.created_at)
    conversations = list(
        (await db.execute(query.order_by(activity.desc()).limit(limit))).scalars().all()
    )
    if not conversations:
        return []

    # Newest message per thread, in one query (Postgres DISTINCT ON).
    last_messages = {
        m.conversation_id: m
        for m in (
            await db.execute(
                select(Message)
                .where(Message.conversation_id.in_([c.id for c in conversations]))
                .distinct(Message.conversation_id)
                .order_by(Message.conversation_id, Message.created_at.desc())
            )
        ).scalars().all()
    }
    patients = await _patients_for(db, office_id, conversations)

    summaries = []
    for c in conversations:
        last = last_messages.get(c.id)
        patient = patients.get(c.id)
        summaries.append(
            ConversationSummary(
                id=c.id,
                whatsapp_id=c.whatsapp_id,
                patient_id=patient.id if patient else None,
                patient_name=patient.name if patient else None,
                last_message_at=last.created_at if last else c.last_message_at,
                last_message_preview=last.content[:PREVIEW_CHARS] if last else None,
                last_message_direction=last.direction if last else None,
            )
        )
    # A thread's last_message_at is not written on every path; the messages are
    # the truth, so re-sort on what they say.
    summaries.sort(key=lambda s: s.last_message_at or _NEVER, reverse=True)

    if redis_client is not None:
        from app.modules.whatsapp.coexistence import conversation_taken_until

        for summary in summaries:
            summary.taken_over_until = await conversation_taken_until(
                office_id, summary.whatsapp_id, redis_client
            )
    return summaries


async def get_conversation_messages(
    db: AsyncSession,
    office_id: UUID,
    conversation_id: UUID,
    before: Optional[datetime] = None,
    limit: int = 50,
) -> list[InboxMessage]:
    """One page of a thread, oldest first; `before` pages further back."""
    conversation = await db.get(Conversation, conversation_id)
    if conversation is None or conversation.office_id != office_id:
        raise NotFoundError("Conversation not found")

    query = select(Message).where(Message.conversation_id == conversation_id)
    if before is not None:
        query = query.where(Message.created_at < before)
    rows = (
        await db.execute(query.order_by(Message.created_at.desc()).limit(limit))
    ).scalars().all()

    return [
        InboxMessage(
            id=m.id,
            content=m.content,
            direction=m.direction,
            author=message_author(m),
            delivery_status=m.delivery_status,
            created_at=m.created_at,
        )
        for m in reversed(rows)
    ]
