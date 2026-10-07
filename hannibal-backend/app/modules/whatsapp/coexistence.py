"""Coexistence: the doctor's own WhatsApp and the assistant on the same number.

Two ways to keep the bot quiet: the office-wide pause (pause_bot / the
dashboard switch), and a per-conversation hold (take_over_conversation) set
when the doctor writes to a patient from the WhatsApp Business app (an
`smb_message_echoes` webhook) or asks the assistant to let them handle one.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional
import uuid
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

import redis.asyncio as redis

from app.utils.dates import now_mx
from app.utils.logger import get_logger
from app.db.models import Conversation, Office

logger = get_logger(__name__)

# Redis key patterns
BOT_PAUSE_KEY_TEMPLATE = "whatsapp:bot_paused:{office_id}"
# One patient's thread held by the doctor (see take_over_conversation).
CONV_TAKEOVER_KEY = "conv_takeover:{office_id}:{whatsapp_id}"

# Default office-wide pause (pause_bot) when no duration is given
DEFAULT_DOCTOR_TAKEOVER_PAUSE_MINUTES = 60
# How long a thread stays with the doctor after their last message to it
DEFAULT_CONVERSATION_TAKEOVER_MINUTES = 120


async def take_over_conversation(
    office_id: uuid.UUID,
    whatsapp_id: str,
    redis_client: redis.Redis,
    minutes: int = DEFAULT_CONVERSATION_TAKEOVER_MINUTES,
) -> datetime:
    """The doctor is talking to this patient: the bot stays out of this one thread.

    Unlike pause_bot (office-wide), every other patient keeps being answered.
    Each call restarts the window, so an ongoing exchange keeps it alive; when
    it lapses the assistant picks the conversation up again.
    """
    key = CONV_TAKEOVER_KEY.format(office_id=office_id, whatsapp_id=whatsapp_id)
    await redis_client.setex(key, timedelta(minutes=minutes), "doctor")
    logger.info("conversation_taken_over", office_id=str(office_id), minutes=minutes)
    return now_mx() + timedelta(minutes=minutes)


async def release_conversation(
    office_id: uuid.UUID, whatsapp_id: str, redis_client: redis.Redis
) -> bool:
    """Hand the thread back to the assistant. Returns whether it was taken."""
    key = CONV_TAKEOVER_KEY.format(office_id=office_id, whatsapp_id=whatsapp_id)
    removed = await redis_client.delete(key)
    logger.info("conversation_released", office_id=str(office_id), was_taken=bool(removed))
    return bool(removed)


async def conversation_taken_until(
    office_id: uuid.UUID, whatsapp_id: str, redis_client: redis.Redis
) -> Optional[datetime]:
    """When the doctor's hold on this thread lapses, or None when the bot answers."""
    key = CONV_TAKEOVER_KEY.format(office_id=office_id, whatsapp_id=whatsapp_id)
    try:
        ttl = await redis_client.ttl(key)
    except Exception as e:
        # Conservative, like check_pause: on error the bot keeps answering.
        logger.error("conversation_takeover_check_error", error=str(e))
        return None
    if ttl is None or ttl < 0:
        return None
    return now_mx() + timedelta(seconds=ttl)


async def check_pause(
    office_id: uuid.UUID,
    redis_client: redis.Redis,
) -> bool:
    """
    Check if bot is currently paused for an office.

    Pauses are stored in Redis with TTL. When expired, the key automatically
    deletes and bot resumes.

    Args:
        office_id: ID of the office
        redis_client: Redis client

    Returns:
        True if bot is paused, False if running normally
    """
    key = BOT_PAUSE_KEY_TEMPLATE.format(office_id=office_id)

    try:
        paused = await redis_client.exists(key)
        return bool(paused)
    except Exception as e:
        logger.error(
            "pause_check_error",
            office_id=str(office_id),
            error=str(e),
        )
        # Conservative: assume NOT paused on error to keep bot running
        return False


async def get_pause_until(
    office_id: uuid.UUID,
    redis_client: redis.Redis,
) -> Optional[datetime]:
    """When the office-wide pause ends, or None when the bot is answering.

    Derived from the pause key's TTL, so the dashboard and the webhook read the
    same single source of truth.
    """
    key = BOT_PAUSE_KEY_TEMPLATE.format(office_id=office_id)
    try:
        ttl = await redis_client.ttl(key)
    except Exception as e:
        logger.error("pause_ttl_error", office_id=str(office_id), error=str(e))
        return None
    # -2: no key (not paused); -1: key without expiry (should not happen).
    if ttl is None or ttl == -2:
        return None
    if ttl == -1:
        return now_mx() + timedelta(days=365)
    return now_mx() + timedelta(seconds=ttl)


async def pause_bot(
    office_id: uuid.UUID,
    minutes: int,
    redis_client: redis.Redis,
) -> bool:
    """
    Manually pause the bot for an office.

    Bot will remain paused until the TTL expires or resume is called.

    Args:
        office_id: ID of the office
        minutes: Duration to pause in minutes
        redis_client: Redis client

    Returns:
        True if pause was successfully set

    Raises:
        ValueError: If minutes is not positive
    """
    if minutes <= 0:
        raise ValueError("pause_minutes must be positive")

    key = BOT_PAUSE_KEY_TEMPLATE.format(office_id=office_id)

    try:
        # Set key with TTL expiration
        await redis_client.setex(
            key,
            timedelta(minutes=minutes),
            "paused",
        )

        logger.info(
            "bot_paused",
            office_id=str(office_id),
            minutes=minutes,
        )

        return True

    except Exception as e:
        logger.error(
            "pause_set_error",
            office_id=str(office_id),
            minutes=minutes,
            error=str(e),
        )
        return False


async def resume_bot(
    office_id: uuid.UUID,
    redis_client: redis.Redis,
) -> bool:
    """
    Manually resume the bot (remove pause status).

    Args:
        office_id: ID of the office
        redis_client: Redis client

    Returns:
        True if resume was successful (or bot wasn't paused)
    """
    key = BOT_PAUSE_KEY_TEMPLATE.format(office_id=office_id)

    try:
        await redis_client.delete(key)

        logger.info(
            "bot_resumed",
            office_id=str(office_id),
        )

        return True

    except Exception as e:
        logger.error(
            "resume_error",
            office_id=str(office_id),
            error=str(e),
        )
        return False


async def get_conversation_by_whatsapp_id(
    office_id: uuid.UUID,
    whatsapp_id: str,
    db: AsyncSession,
) -> Optional[Conversation]:
    """
    Fetch conversation by WhatsApp phone number.

    Args:
        office_id: ID of the office
        whatsapp_id: WhatsApp phone number ID
        db: Database session

    Returns:
        Conversation object if found, None otherwise
    """
    try:
        result = await db.execute(
            select(Conversation).where(
                Conversation.office_id == office_id,
                Conversation.whatsapp_id == whatsapp_id,
            )
        )
        return result.scalars().first()
    except Exception as e:
        logger.error(
            "get_conversation_error",
            office_id=str(office_id),
            whatsapp_id=whatsapp_id,
            error=str(e),
        )
        return None
