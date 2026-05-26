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

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Conversation, Message

MX_TZ = ZoneInfo("America/Mexico_City")
SERVICE_WINDOW = timedelta(hours=24)


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
