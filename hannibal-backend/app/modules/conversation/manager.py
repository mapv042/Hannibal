"""Tool-use based conversation manager — replaces the intent/state-machine approach."""

from __future__ import annotations

import uuid
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.utils.dates import now_mx
from app.utils.logger import get_logger
from app.core.exceptions import ConversationError
from app.db.models import Appointment, Office, Patient, Conversation, Message
from app.modules.ai.prompts.base import build_system_prompt
from app.modules.ai.tools import TOOL_DEFINITIONS, ToolContext, execute_tool
from app.modules.conversation.base_manager import BaseToolConversationManager
from app.modules.conversation.session_store import SessionStore
from app.modules.conversation.schemas import SessionContext
from app.modules.whatsapp.meta_client import MetaCloudClient

logger = get_logger(__name__)

MAX_HISTORY_TURNS = 40


class ConversationManager(BaseToolConversationManager):
    """
    Tool-use based conversation manager for patients.

    The LLM decides which tools to call; results are fed back until it
    produces a final text response. Persisted session history contains only
    plain text turns (see BaseToolConversationManager.sanitize_history) — the
    tool chain lives in a per-turn working copy.
    """

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

    def __init__(
        self,
        session_store: SessionStore,
        meta_client: MetaCloudClient,
        ai_service=None,
    ):
        super().__init__(meta_client, ai_service)
        self.session_store = session_store

    def _non_text_placeholder(self, msg_type: str, caption: str) -> str:
        label = self._MESSAGE_TYPE_LABELS.get(msg_type, msg_type)
        if caption:
            return f"[El paciente envió un {label} con el texto: \"{caption}\"]"
        return f"[El paciente envió un {label}]"

    async def process(
        self,
        office: Office,
        message: dict[str, Any],
        db: AsyncSession,
    ) -> None:
        """Process one incoming WhatsApp message using the tool-use loop.

        `message` is the raw message dict from the Meta webhook payload.
        Bot pause is enforced upstream (webhook router, Redis key) — single
        source of truth; see whatsapp/coexistence.check_pause.
        """
        try:
            # 1. Extract message (transcribes voice notes)
            message_data = await self.extract_message(message, office)
            whatsapp_id = message_data["from"]
            message_text = message_data["text"]
            message_id = message_data["id"]

            logger.info(
                "processing_message_v2",
                office_id=str(office.id),
                whatsapp_id=whatsapp_id,
                message_id=message_id,
            )

            # 2. Get or create session
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

            # 3. Get or create patient
            patient = await self._get_or_create_patient(db, office.id, whatsapp_id)
            if patient:
                session.patient_id = patient.id
                conversation_obj.patient_id = patient.id

            # 4. Save incoming message
            await self._save_incoming_message(db, office.id, whatsapp_id, message_text, message_id)

            # 4.5 Check if patient is new or returning
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

            # 5. Build system prompt and append the user turn to history
            active_appt_id = (
                str(session.active_appointment_id)
                if session.active_appointment_id
                else None
            )
            system_prompt = build_system_prompt(
                office,
                active_appointment_id=active_appt_id,
                is_returning_patient=is_returning,
                patient_name=patient.name if patient else None,
            )
            session.claude_history = self.sanitize_history(session.claude_history)
            session.claude_history.append({"role": "user", "content": message_text})

            # 6. Tool-use loop on a per-turn working copy — the provider-specific
            # tool chain it accumulates is discarded after the turn.
            tool_ctx = ToolContext(
                db=db,
                office=office,
                patient_id=session.patient_id,
                whatsapp_id=whatsapp_id,
                redis_client=self.session_store.redis_client,
            )
            working_messages = list(session.claude_history)
            response_text = await self.run_tool_loop(
                system_prompt,
                working_messages,
                TOOL_DEFINITIONS,
                execute_tool,
                tool_ctx,
                log_prefix="patient",
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

            # 7. Append the assistant turn (text only) and trim
            session.claude_history.append({"role": "assistant", "content": response_text})
            if len(session.claude_history) > MAX_HISTORY_TURNS:
                session.claude_history = session.claude_history[-MAX_HISTORY_TURNS:]

            # 8. Send response. Tool side effects (bookings, cancellations) are
            # already in this transaction, so the assistant turn stays in the
            # history either way — but a failed send is recorded as "failed",
            # never as sent.
            sent_message_id: Optional[str] = None
            send_failed = False
            try:
                sent_message_id = await self.meta_client.send_text_message(
                    phone_number_id=office.whatsapp_phone_id,
                    token=office.whatsapp_token,
                    to=whatsapp_id,
                    text=response_text,
                )
            except Exception as e:
                send_failed = True
                logger.error("failed_to_send_response", error=str(e), whatsapp_id=whatsapp_id)

            # 9. Save outgoing message with its real delivery outcome
            await self._save_outgoing_message(
                db,
                conversation_obj.id,
                response_text,
                whatsapp_message_id=sent_message_id,
                delivery_status="failed" if send_failed else "sent",
            )

            # 10. Update conversation state
            session.last_message_at = now_mx().isoformat()
            conversation_obj.last_message_at = now_mx()

            await db.commit()

            # 11. Save session
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

    # ------------------------------------------------------------------
    # Persistence helpers
    # ------------------------------------------------------------------

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
        whatsapp_message_id: Optional[str] = None,
        delivery_status: Optional[str] = None,
    ) -> None:
        message = Message(
            id=uuid.uuid4(),
            conversation_id=conversation_id,
            content=content,
            type="text",
            direction="outgoing",
            whatsapp_message_id=whatsapp_message_id,
            delivery_status=delivery_status,
        )
        db.add(message)
        await db.flush()
