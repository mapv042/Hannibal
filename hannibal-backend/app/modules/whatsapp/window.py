"""WhatsApp customer-service window helper.

A business may send free-form messages only while the 24h customer-service
window is open — i.e. the patient sent an inbound message within the last 24h.
While open, free text is allowed and free; outside it, only an approved template
can be delivered (and templates are billed per message).

Shared by the reminder Celery tasks and the doctor-facing tools so the
free-text-vs-template decision is made consistently in one place.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import redis.asyncio as aioredis
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Conversation, Message

MX_TZ = ZoneInfo("America/Mexico_City")
SERVICE_WINDOW = timedelta(hours=24)

# Redis key holding the timestamp of the doctor's last inbound message to the
# bot, per office. The doctor talks to the bot's number from their personal
# phone, but DoctorConversationManager keeps that thread in Redis only (it does
# not persist Message rows), so service_window_open() — which reads the Message
# table — cannot see it. We track the doctor window with this key instead.
DOCTOR_LAST_INBOUND_KEY = "doctor_last_inbound:{office_id}"


async def service_window_open(
    db: AsyncSession,
    office_id,
    whatsapp_id: str,
    window: timedelta = SERVICE_WINDOW,
) -> bool:
    """True if the patient sent an inbound message within the window.

    When open, free-form (free) text can be sent; otherwise an approved
    template is required to reach the patient at all.
    """
    result = await db.execute(
        select(Message.created_at)
        .join(Conversation, Message.conversation_id == Conversation.id)
        .where(
            and_(
                Conversation.office_id == office_id,
                Conversation.whatsapp_id == whatsapp_id,
                Message.direction == "incoming",
            )
        )
        .order_by(Message.created_at.desc())
        .limit(1)
    )
    last_inbound = result.scalar_one_or_none()
    if last_inbound is None:
        return False
    return (datetime.now(MX_TZ) - last_inbound) < window


async def record_doctor_inbound(
    redis_client: aioredis.Redis,
    office_id,
    window: timedelta = SERVICE_WINDOW,
) -> None:
    """Mark that the doctor just messaged the bot (opens their 24h window).

    Stored as a Redis key whose mere presence means "within the window": it
    expires exactly when the window would close. Best-effort — a failure here
    must not break message handling.
    """
    try:
        await redis_client.set(
            DOCTOR_LAST_INBOUND_KEY.format(office_id=office_id),
            datetime.now(MX_TZ).isoformat(),
            ex=int(window.total_seconds()),
        )
    except Exception:
        pass


async def doctor_service_window_open(
    redis_client: aioredis.Redis,
    office_id,
) -> bool:
    """True if the doctor sent an inbound message within the service window.

    Mirrors service_window_open() for the doctor thread, using the Redis key set
    by record_doctor_inbound(). On any Redis error we assume the window is
    closed so the caller falls back to an approved template (safe default).
    """
    try:
        exists = await redis_client.exists(DOCTOR_LAST_INBOUND_KEY.format(office_id=office_id))
        return bool(exists)
    except Exception:
        return False
