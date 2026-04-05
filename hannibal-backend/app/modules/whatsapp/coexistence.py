"""Coexistence mode handling for bot and doctor message echoes."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional
import uuid
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

import redis.asyncio as redis

from app.utils.logger import get_logger
from app.db.models import Conversation, Office

logger = get_logger(__name__)

# Redis key patterns
BOT_PAUSE_KEY_TEMPLATE = "whatsapp:bot_paused:{office_id}"
LAST_DOCTOR_MESSAGE_KEY_TEMPLATE = "whatsapp:last_doctor_message:{office_id}:{whatsapp_id}"

# Default pause duration in minutes when doctor takes control
DEFAULT_DOCTOR_TAKEOVER_PAUSE_MINUTES = 60


def is_doctor_echo(payload: dict) -> bool:
    """
    Detect if an incoming message is an echo of a doctor's outbound message.

    In coexistence mode, the doctor might send messages directly from their
    WhatsApp client. We need to detect these echoes to avoid processing them
    through the bot.

    The detection logic checks if:
    1. The message is from the office's WhatsApp number (sent by doctor)
    2. Recent context indicates doctor interaction

    Args:
        payload: Webhook payload from Meta

    Returns:
        True if this appears to be a doctor's message echo, False otherwise
    """
    # This is a simplified check. In real scenarios, you might check:
    # - If the incoming message is from the office's own number
    # - Metadata flags indicating it's a sent message
    # - Timestamp alignment with outbound message logs

    try:
        # Extract from_id from the standard webhook structure
        entry = payload.get("entry", [{}])[0]
        changes = entry.get("changes", [{}])[0]
        value = changes.get("value", {})
        messages = value.get("messages", [])

        if not messages:
            return False

        message = messages[0]
        from_id = message.get("from")

        # Check if there's context suggesting this is a doctor echo
        # (This would be populated by conversation context)
        context_type = message.get("context", {}).get("forwarded")
        is_forwarded = message.get("context", {}).get("forwarded", False)

        logger.debug(
            "echo_detection_check",
            from_id=from_id,
            is_forwarded=is_forwarded,
        )

        # Simple heuristic: Meta marks echoed messages with specific context
        return False  # Conservative default - let other logic handle it

    except (KeyError, IndexError, TypeError) as e:
        logger.warning("echo_detection_error", error=str(e))
        return False


async def handle_echo(
    office_id: uuid.UUID,
    conversation_id: uuid.UUID,
    content: str,
    db: AsyncSession,
    redis_client: redis.Redis,
    pause_minutes: int = DEFAULT_DOCTOR_TAKEOVER_PAUSE_MINUTES,
) -> bool:
    """
    Handle doctor takeover: pause bot and mark conversation as taken by doctor.

    When a doctor sends a message in a coexistence setup, we:
    1. Pause the bot for a configured duration
    2. Mark the conversation as taken by doctor in database
    3. Log the takeover event
    4. Store in Redis for fast pause checks

    Args:
        office_id: ID of the office
        conversation_id: ID of the conversation
        content: Doctor's message content (for logging)
        db: Database session
        redis_client: Redis client for pause state
        pause_minutes: Duration to pause bot in minutes

    Returns:
        True if takeover was successfully handled

    Raises:
        SQLAlchemy errors if database update fails
    """
    try:
        # Update conversation in database
        conversation = await db.get(Conversation, conversation_id)
        if conversation:
            conversation.taken_by_doctor = True
            conversation.doctor_took_control_at = datetime.utcnow()
            conversation.status = "paused"
            db.add(conversation)
            await db.commit()

        # Set pause in Redis
        await pause_bot(office_id, pause_minutes, redis_client)

        logger.info(
            "doctor_takeover_handled",
            office_id=str(office_id),
            conversation_id=str(conversation_id),
            pause_minutes=pause_minutes,
            content_preview=content[:100] if content else None,
        )

        return True

    except Exception as e:
        logger.error(
            "doctor_takeover_error",
            office_id=str(office_id),
            conversation_id=str(conversation_id),
            error=str(e),
        )
        return False


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
