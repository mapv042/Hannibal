"""Tool-use based conversation manager — replaces the intent/state-machine approach."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.utils.dates import now_mx
from app.utils.logger import get_logger
from app.core.exceptions import ConversationError
from app.db.models import Appointment, Office, Patient, Conversation, Message
from app.modules.ai import get_ai_service
from app.modules.ai.prompts.base import build_system_prompt
from app.modules.ai.tools import TOOL_DEFINITIONS, ToolContext, execute_tool
from app.modules.conversation.session_store import SessionStore
from app.modules.conversation.schemas import SessionContext
from app.modules.whatsapp.meta_client import MetaCloudClient

if TYPE_CHECKING:
    from redis.asyncio import Redis

logger = get_logger(__name__)

MAX_TOOL_ITERATIONS = 5


class ConversationManager:
    """
    Tool-use based conversation manager.

    Instead of detecting intents and running a state machine, this manager
    sends the user message to the LLM with tool definitions. The LLM decides
    which tools to call (if any), and the results are fed back until the LLM
    produces a final text response.
    """

    def __init__(
        self,
        session_store: SessionStore,
        meta_client: MetaCloudClient,
        ai_service=None,
    ):
        self.session_store = session_store
        self.meta_client = meta_client
        self.ai_service = ai_service or get_ai_service()

    async def process(
        self,
        office: Office,
        payload: dict[str, Any],
        db: AsyncSession,
    ) -> None:
        """Process incoming WhatsApp message using tool-use loop."""
        try:
            # 1. Extract message
            message_data = self._extract_message_from_payload(payload)
            whatsapp_id = message_data["from"]
            message_text = message_data["text"]
            message_id = message_data["id"]

            logger.info(
                "processing_message_v2",
                office_id=str(office.id),
                whatsapp_id=whatsapp_id,
                message_id=message_id,
            )

            # 2. Check if bot is paused
            if office.bot_paused_until:
                now = now_mx()
                if now < office.bot_paused_until:
                    logger.info("bot_paused", office_id=str(office.id))
                    await self._save_incoming_message(db, office.id, whatsapp_id, message_text, message_id)
                    return

            # 3. Get or create session
            session = await self.session_store.get_session(whatsapp_id, str(office.id))
            conversation_obj: Optional[Conversation] = None

            if session:
                stmt = select(Conversation).where(Conversation.id == session.conversation_id)
                result = await db.execute(stmt)
                conversation_obj = result.scalar_one_or_none()
            else:
                conversation_obj = await self._get_or_create_conversation(db, office.id, whatsapp_id)
                session = SessionContext(
                    conversation_id=conversation_obj.id,
                    office_id=office.id,
                    whatsapp_id=whatsapp_id,
                    status="active",
                    claude_history=[],
                    collected_data={},
                )

            # 4. Get or create patient
            patient = await self._get_or_create_patient(db, office.id, whatsapp_id)
            if patient:
                session.patient_id = patient.id
                conversation_obj.patient_id = patient.id

            # 5. Save incoming message
            await self._save_incoming_message(db, office.id, whatsapp_id, message_text, message_id)

            # 5.5 Check if patient is new or returning
            is_returning = False
            if session.patient_id:
                past_appt = await db.execute(
                    select(Appointment).where(
                        (Appointment.office_id == office.id)
                        & (Appointment.patient_id == session.patient_id)
                        & (Appointment.status.in_(["completed", "confirmed", "scheduled"]))
                    ).limit(1)
                )
                is_returning = past_appt.scalars().first() is not None

            # 6. Build system prompt and add user message to history
            active_appt_id = (
                str(session.active_appointment_id)
                if session.active_appointment_id
                else None
            )
            system_prompt = build_system_prompt(
                office,
                active_appointment_id=active_appt_id,
                is_returning_patient=is_returning,
            )
            session.claude_history.append({"role": "user", "content": message_text})

            # 7. Tool-use loop
            tool_ctx = ToolContext(
                db=db,
                office=office,
                patient_id=session.patient_id,
                whatsapp_id=whatsapp_id,
            )

            response_text = await self._tool_use_loop(
                system_prompt, session.claude_history, tool_ctx
            )

            # Update patient_id if a tool created the patient
            if tool_ctx.patient_id and tool_ctx.patient_id != session.patient_id:
                session.patient_id = tool_ctx.patient_id

            # Clear confirmation state if the appointment was confirmed or cancelled
            if session.active_appointment_id:
                appt = await db.get(Appointment, session.active_appointment_id)
                if not appt or appt.status in ("confirmed", "cancelled"):
                    session.active_appointment_id = None
                    session.status = "active"

            # Fallback
            if not response_text or not response_text.strip():
                response_text = "Disculpa, no pude procesar tu mensaje. ¿Podrías repetirlo?"
                logger.warning("empty_response_fallback_v2", office_id=str(office.id))

            # 8. Append assistant response to history (only the text, not tool calls)
            session.claude_history.append({"role": "assistant", "content": response_text})

            # Trim history
            if len(session.claude_history) > 40:
                session.claude_history = self._trim_history(session.claude_history, 40)

            # 9. Send response
            try:
                await self.meta_client.send_text_message(
                    phone_number_id=office.whatsapp_phone_id,
                    token=office.whatsapp_token,
                    to=whatsapp_id,
                    text=response_text,
                )
            except Exception as e:
                logger.error("failed_to_send_response", error=str(e), whatsapp_id=whatsapp_id)

            # 10. Save outgoing message
            await self._save_outgoing_message(db, conversation_obj.id, response_text)

            # 11. Update conversation state
            session.last_message_at = now_mx().isoformat()
            conversation_obj.last_message_at = now_mx()

            await db.commit()

            # 12. Save session
            await self.session_store.save_session(whatsapp_id, str(office.id), session)

            logger.info(
                "message_processed_v2",
                office_id=str(office.id),
                whatsapp_id=whatsapp_id,
            )

        except ConversationError:
            raise
        except Exception as e:
            logger.error("conversation_processing_failed_v2", error=str(e), office_id=str(office.id))
            raise ConversationError(f"Failed to process conversation: {str(e)}") from e

    async def _tool_use_loop(
        self,
        system_prompt: str,
        messages: list[dict],
        ctx: ToolContext,
    ) -> str:
        """
        Run the tool-use loop until the LLM produces a final text response.

        Returns the final text to send to the patient.
        """
        for iteration in range(MAX_TOOL_ITERATIONS):
            response = await self.ai_service.chat_with_tools(
                system_prompt=system_prompt,
                messages=messages,
                tools=TOOL_DEFINITIONS,
            )

            if not response.tool_calls:
                # Final text response
                return response.text or ""

            # Execute each tool call
            logger.info(
                "tool_calls",
                iteration=iteration + 1,
                tools=[tc.name for tc in response.tool_calls],
            )

            tool_results = []
            for tc in response.tool_calls:
                result = await execute_tool(tc.name, tc.arguments, ctx)
                tool_results.append({
                    "tool_call_id": tc.id,
                    "result": result,
                })

            # Append assistant message + tool results to history
            result_messages = self.ai_service.build_tool_result_messages(
                response.raw_message, tool_results
            )
            messages.extend(result_messages)

        # Safety: max iterations reached
        logger.warning("tool_use_loop_max_iterations", max=MAX_TOOL_ITERATIONS)
        return "Disculpa, tuve un problema procesando tu solicitud. ¿Podrías intentarlo de nuevo?"

    @staticmethod
    def _trim_history(messages: list[dict], max_len: int) -> list[dict]:
        """Trim history to max_len without orphaning tool messages.

        After slicing, the first message might be a 'tool' response whose
        preceding 'assistant' (with tool_calls) was cut off.  OpenAI rejects
        this.  We skip forward until we find a non-tool message.
        """
        trimmed = messages[-max_len:]
        while trimmed and trimmed[0].get("role") == "tool":
            trimmed.pop(0)
        # Also guard against starting with an assistant tool_calls message
        # whose tool results were partially cut
        if trimmed and trimmed[0].get("role") == "assistant" and trimmed[0].get("tool_calls"):
            trimmed.pop(0)
            while trimmed and trimmed[0].get("role") == "tool":
                trimmed.pop(0)
        return trimmed

    # ------------------------------------------------------------------
    # Helper methods (reused from original manager, simplified)
    # ------------------------------------------------------------------

    # Human-readable labels for WhatsApp message types
    _MESSAGE_TYPE_LABELS: dict[str, str] = {
        "audio": "mensaje de voz",
        "image": "imagen",
        "video": "video",
        "document": "documento",
        "sticker": "sticker",
        "location": "ubicación",
        "contacts": "contacto",
        "reaction": "reacción",
    }

    @staticmethod
    def _extract_message_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
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
                # Convert non-text messages to a description the LLM can respond to
                label = ConversationManager._MESSAGE_TYPE_LABELS.get(msg_type, msg_type)
                caption = ""
                # Some types (image, video, document) can have a caption
                if msg_type in ("image", "video", "document"):
                    caption = (message.get(msg_type) or {}).get("caption", "")
                if caption:
                    text = f"[El paciente envió un {label} con el texto: \"{caption}\"]"
                else:
                    text = f"[El paciente envió un {label}]"

            return {
                "from": message["from"],
                "text": text,
                "id": message["id"],
                "timestamp": message["timestamp"],
            }
        except (KeyError, IndexError) as e:
            raise ConversationError(f"Invalid message payload: {str(e)}") from e

    async def _get_or_create_conversation(
        self, db: AsyncSession, office_id: uuid.UUID, whatsapp_id: str,
    ) -> Conversation:
        stmt = select(Conversation).where(
            (Conversation.office_id == office_id)
            & (Conversation.whatsapp_id == whatsapp_id)
            & (Conversation.status != "archived")
        )
        result = await db.execute(stmt)
        conversation = result.scalar_one_or_none()
        if conversation:
            return conversation

        conversation = Conversation(
            id=uuid.uuid4(),
            office_id=office_id,
            whatsapp_id=whatsapp_id,
            status="active",
        )
        db.add(conversation)
        await db.flush()
        return conversation

    async def _get_or_create_patient(
        self, db: AsyncSession, office_id: uuid.UUID, whatsapp_id: str,
    ) -> Optional[Patient]:
        stmt = select(Patient).where(
            (Patient.office_id == office_id)
            & (Patient.whatsapp_id == whatsapp_id)
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def _save_incoming_message(
        self, db: AsyncSession, office_id: uuid.UUID, whatsapp_id: str,
        content: str, message_id: str,
    ) -> None:
        stmt = select(Conversation).where(
            (Conversation.office_id == office_id)
            & (Conversation.whatsapp_id == whatsapp_id)
        )
        result = await db.execute(stmt)
        conversation = result.scalar_one_or_none()
        if conversation:
            message = Message(
                id=uuid.uuid4(),
                conversation_id=conversation.id,
                content=content,
                type="text",
                direction="incoming",
                whatsapp_message_id=message_id,
            )
            db.add(message)
            await db.flush()

    async def _save_outgoing_message(
        self, db: AsyncSession, conversation_id: uuid.UUID, content: str,
    ) -> None:
        message = Message(
            id=uuid.uuid4(),
            conversation_id=conversation_id,
            content=content,
            type="text",
            direction="outgoing",
        )
        db.add(message)
        await db.flush()
