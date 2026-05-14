"""Conversation manager for doctor commands via WhatsApp."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
import redis.asyncio as redis

from app.utils.logger import get_logger
from app.core.exceptions import ConversationError
from app.db.models import Office
from app.modules.ai import get_ai_service
from app.modules.ai.prompts.doctor_v2 import build_doctor_system_prompt
from app.modules.ai.doctor_tools import (
    DOCTOR_TOOL_DEFINITIONS,
    DoctorToolContext,
    execute_doctor_tool,
)
from app.modules.whatsapp.meta_client import MetaCloudClient

logger = get_logger(__name__)

MAX_TOOL_ITERATIONS = 5
DOCTOR_SESSION_KEY = "doctor_session:{office_id}"
DOCTOR_SESSION_TTL = 86400  # 24 hours


class DoctorConversationManager:
    """
    Handles doctor commands via WhatsApp using LLM + tools.

    The doctor messages the bot's WhatsApp number from their personal phone.
    Messages are detected by matching `from` with `office.owner_phone`.
    """

    def __init__(
        self,
        meta_client: MetaCloudClient,
        redis_client: redis.Redis,
        ai_service=None,
    ):
        self.meta_client = meta_client
        self.redis_client = redis_client
        self.ai_service = ai_service or get_ai_service()

    async def process(
        self,
        office: Office,
        payload: dict[str, Any],
        db: AsyncSession,
    ) -> None:
        """Process incoming doctor message."""
        try:
            message_data = self._extract_message(payload)
            message_text = message_data["text"]
            whatsapp_id = message_data["from"]

            logger.info(
                "doctor_message_received",
                office_id=str(office.id),
                whatsapp_id=whatsapp_id,
            )

            # Get or initialize conversation history from Redis
            history = await self._get_history(office.id)
            history.append({"role": "user", "content": message_text})

            # Build system prompt and tool context
            system_prompt = build_doctor_system_prompt(office)
            tool_ctx = DoctorToolContext(
                db=db,
                office=office,
                redis_client=self.redis_client,
                meta_client=self.meta_client,
            )

            # Tool-use loop
            response_text = await self._tool_use_loop(system_prompt, history, tool_ctx)

            if not response_text or not response_text.strip():
                response_text = "No pude procesar tu mensaje. Intenta de nuevo."

            # Append response and save history
            history.append({"role": "assistant", "content": response_text})
            if len(history) > 30:
                history = self._trim_history(history, 30)
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

    async def _tool_use_loop(
        self,
        system_prompt: str,
        messages: list[dict],
        ctx: DoctorToolContext,
    ) -> str:
        """Run tool-use loop until LLM produces final text."""
        for iteration in range(MAX_TOOL_ITERATIONS):
            response = await self.ai_service.chat_with_tools(
                system_prompt=system_prompt,
                messages=messages,
                tools=DOCTOR_TOOL_DEFINITIONS,
            )

            if not response.tool_calls:
                return response.text or ""

            logger.info(
                "doctor_tool_calls",
                iteration=iteration + 1,
                tools=[tc.name for tc in response.tool_calls],
            )

            tool_results = []
            for tc in response.tool_calls:
                result = await execute_doctor_tool(tc.name, tc.arguments, ctx)
                tool_results.append({
                    "tool_call_id": tc.id,
                    "result": result,
                })

            # Append to history
            result_messages = self.ai_service.build_tool_result_messages(
                response.raw_message, tool_results
            )
            messages.extend(result_messages)

        logger.warning("doctor_tool_loop_max_iterations")
        return "Se alcanzó el límite de operaciones. Intenta de nuevo."

    @staticmethod
    def _extract_message(payload: dict[str, Any]) -> dict[str, Any]:
        """Extract message text from webhook payload."""
        try:
            entry = payload["entry"][0]
            changes = entry["changes"][0]
            value = changes["value"]
            messages = value.get("messages", [])
            if not messages:
                raise ValueError("No messages in payload")
            message = messages[0]
            msg_type = message.get("type", "text")

            if msg_type == "text":
                text = message["text"]["body"]
            else:
                # Doctor sent non-text — extract caption or inform
                caption = ""
                if msg_type in ("image", "video", "document"):
                    caption = (message.get(msg_type) or {}).get("caption", "")
                text = caption if caption else f"[Mensaje de tipo {msg_type}]"

            return {
                "from": message["from"],
                "text": text,
                "id": message["id"],
            }
        except (KeyError, IndexError) as e:
            raise ConversationError(f"Invalid message payload: {str(e)}") from e

    @staticmethod
    def _trim_history(messages: list[dict], max_len: int) -> list[dict]:
        """Trim history without orphaning tool messages.

        After slicing, the first message might be a 'tool' response whose
        preceding 'assistant' (with tool_calls) was cut off. OpenAI rejects
        this. We skip forward until we find a valid starting message.
        """
        trimmed = messages[-max_len:]
        # Drop orphaned tool results at the start
        while trimmed and trimmed[0].get("role") == "tool":
            trimmed.pop(0)
        # If we now start with an assistant tool_calls message whose
        # tool results were partially cut, drop it too
        if trimmed and trimmed[0].get("role") == "assistant" and trimmed[0].get("tool_calls"):
            trimmed.pop(0)
            while trimmed and trimmed[0].get("role") == "tool":
                trimmed.pop(0)
        return trimmed

    async def _get_history(self, office_id: uuid.UUID) -> list[dict]:
        """Load doctor conversation history from Redis."""
        import json
        key = DOCTOR_SESSION_KEY.format(office_id=office_id)
        try:
            data = await self.redis_client.get(key)
            if data:
                history = json.loads(data)
                # Sanitize: drop orphaned tool messages at the start
                while history and history[0].get("role") == "tool":
                    history.pop(0)
                if history and history[0].get("role") == "assistant" and history[0].get("tool_calls"):
                    history.pop(0)
                    while history and history[0].get("role") == "tool":
                        history.pop(0)
                return history
        except Exception as e:
            logger.warning("doctor_session_load_error", error=str(e))
        return []

    async def _save_history(self, office_id: uuid.UUID, history: list[dict]) -> None:
        """Save doctor conversation history to Redis."""
        import json
        key = DOCTOR_SESSION_KEY.format(office_id=office_id)
        try:
            await self.redis_client.setex(key, DOCTOR_SESSION_TTL, json.dumps(history))
        except Exception as e:
            logger.warning("doctor_session_save_error", error=str(e))
