"""Conversation manager for doctor commands via WhatsApp."""

from __future__ import annotations

import json
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
import redis.asyncio as redis

from app.utils.logger import get_logger
from app.core.exceptions import ConversationError
from app.db.models import Office
from app.modules.ai.prompts.doctor import build_doctor_system_prompt
from app.modules.ai.doctor_tools import (
    DOCTOR_TOOL_DEFINITIONS,
    DoctorToolContext,
    execute_doctor_tool,
)
from app.modules.conversation.base_manager import BaseToolConversationManager
from app.modules.whatsapp.meta_client import MetaCloudClient
from app.modules.whatsapp.window import record_doctor_inbound
from app.modules.urgencies.service import get_pending_urgencies

logger = get_logger(__name__)

DOCTOR_SESSION_KEY = "doctor_session:{office_id}"
DOCTOR_SESSION_TTL = 86400  # 24 hours
MAX_HISTORY_TURNS = 30


class DoctorConversationManager(BaseToolConversationManager):
    """
    Handles doctor commands via WhatsApp using LLM + tools.

    The doctor messages the bot's WhatsApp number from their personal phone.
    Messages are detected by matching `from` with `office.owner_phone`.
    Persisted history contains only plain text turns (see
    BaseToolConversationManager.sanitize_history).
    """

    def __init__(
        self,
        meta_client: MetaCloudClient,
        redis_client: redis.Redis,
        ai_service=None,
    ):
        super().__init__(meta_client, ai_service)
        self.redis_client = redis_client

    def _non_text_placeholder(self, msg_type: str, caption: str) -> str:
        # The doctor's caption is usually the instruction itself.
        if caption:
            return caption
        return f"[Mensaje de tipo {msg_type}]"

    async def process(
        self,
        office: Office,
        message: dict[str, Any],
        db: AsyncSession,
    ) -> None:
        """Process one incoming doctor message (raw webhook message dict)."""
        try:
            message_data = await self.extract_message(message, office)
            message_text = message_data["text"]
            whatsapp_id = message_data["from"]

            logger.info(
                "doctor_message_received",
                office_id=str(office.id),
                whatsapp_id=whatsapp_id,
            )

            # Record the doctor's inbound so business-initiated urgency
            # notifications know their 24h service window is open.
            await record_doctor_inbound(self.redis_client, office.id)

            # Get conversation history from Redis (text turns only)
            history = await self._get_history(office.id)
            history.append({"role": "user", "content": message_text})

            # Build system prompt and tool context. Pending urgent requests are
            # injected so the doctor can approve/reject them in this turn.
            pending_urgencies = await get_pending_urgencies(office.id, db)
            system_prompt = build_doctor_system_prompt(office, pending_urgencies=pending_urgencies)
            tool_ctx = DoctorToolContext(
                db=db,
                office=office,
                redis_client=self.redis_client,
                meta_client=self.meta_client,
            )

            # Tool-use loop on a per-turn working copy (tool chain discarded)
            working_messages = list(history)
            response_text = await self.run_tool_loop(
                system_prompt,
                working_messages,
                DOCTOR_TOOL_DEFINITIONS,
                execute_doctor_tool,
                tool_ctx,
                log_prefix="doctor",
            )

            if not response_text or not response_text.strip():
                response_text = "No pude procesar tu mensaje. Intenta de nuevo."

            # Append the assistant turn (text only), trim, save
            history.append({"role": "assistant", "content": response_text})
            if len(history) > MAX_HISTORY_TURNS:
                history = history[-MAX_HISTORY_TURNS:]
            await self._save_history(office.id, history)

            # Send response to doctor
            try:
                await self.meta_client.send_text_message(
                    phone_number_id=office.whatsapp_phone_id,
                    token=office.whatsapp_token,
                    to=whatsapp_id,
                    text=response_text,
                )
            except Exception as e:
                logger.error("doctor_send_failed", error=str(e))

            await db.commit()

            logger.info("doctor_message_processed", office_id=str(office.id))

        except Exception as e:
            logger.error("doctor_processing_failed", error=str(e), exc_info=True)
            raise ConversationError(f"Failed to process doctor message: {str(e)}") from e

    async def _get_history(self, office_id: uuid.UUID) -> list[dict]:
        """Load doctor conversation history from Redis (sanitized to text turns)."""
        key = DOCTOR_SESSION_KEY.format(office_id=office_id)
        try:
            data = await self.redis_client.get(key)
            if data:
                return self.sanitize_history(json.loads(data))
        except Exception as e:
            logger.warning("doctor_session_load_error", error=str(e))
        return []

    async def _save_history(self, office_id: uuid.UUID, history: list[dict]) -> None:
        """Save doctor conversation history to Redis."""
        key = DOCTOR_SESSION_KEY.format(office_id=office_id)
        try:
            await self.redis_client.setex(key, DOCTOR_SESSION_TTL, json.dumps(history))
        except Exception as e:
            logger.warning("doctor_session_save_error", error=str(e))
