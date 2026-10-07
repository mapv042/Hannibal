"""Retention of WhatsApp messages (LFPDPPP: keep data only as long as needed).

Messages carry health data in free text. The office needs them to supervise
the assistant and to settle "the bot told me another time" — not forever. The
privacy notice promises deletion after settings.message_retention_days.
"""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import delete

from app.config import settings
from app.db.models import Message
from app.utils.dates import now_mx


async def prune_old_messages(db) -> int:
    """Delete messages older than the retention window. Returns rows deleted."""
    cutoff = now_mx() - timedelta(days=settings.message_retention_days)
    result = await db.execute(delete(Message).where(Message.created_at < cutoff))
    await db.commit()
    return result.rowcount or 0
