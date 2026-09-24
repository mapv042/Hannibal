"""Tool-use based conversation manager — replaces the intent/state-machine approach."""

from __future__ import annotations

import uuid
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.utils.dates import now_mx
from app.utils.phone import phone_match_variants
from app.utils.logger import get_logger
from app.core.constants import DEFAULT_REMINDER_RULES
from app.core.exceptions import AIServiceError, ConversationError
from app.db.models import (
    Appointment,
    AvailabilitySchedule,
    Conversation,
    Message,
    Office,
    Patient,
    ReminderRule,
)
from app.modules.ai.prompts.base import WAITING_ARRIVAL_STATUS, build_system_prompt
from app.modules.ai.tool_helpers import is_returning_patient
from app.modules.ai.tools import (
    MUTATING_TOOLS,
    TOOL_CLAIMS,
    TOOL_DEFINITIONS,
    ToolContext,
    execute_tool,
)
from app.modules.conversation.tracing import persist_trace
from app.modules.conversation.base_manager import BaseToolConversationManager
from app.modules.conversation.session_store import SessionStore
from app.modules.conversation.schemas import SessionContext
from app.modules.whatsapp.transport import WhatsAppClient

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
        meta_client: WhatsAppClient,
        ai_service=None,
    ):
        super().__init__(meta_client, ai_service)
        self.session_store = session_store

    def _non_text_placeholder(self, msg_type: str, caption: str) -> str:
        label = self._MESSAGE_TYPE_LABELS.get(msg_type, msg_type)
        if caption:
            return f"[El paciente envió un {label} con el texto: \"{caption}\"]"
        return f"[El paciente envió un {label}]"

    UNGROUNDED_FALLBACK = (
        "Disculpa, tuve un problema y no se realizó ningún cambio. "
        "¿Me lo repites, por favor?"
    )
    # Sent when the model itself can't be reached. The patient's message is
    # kept (history + dashboard), so the next message resumes with context.
    AI_UNAVAILABLE_REPLY = (
        "Disculpa, estoy teniendo un problema técnico en este momento. "
        "Escríbeme de nuevo en unos minutos, por favor."
    )

    async def process(
        self,
        office: Office,
        message: dict[str, Any] | list[dict[str, Any]],
        db: AsyncSession,
    ) -> None:
        """Process one turn: one incoming WhatsApp message, or a burst of them.

        `message` is the raw message dict from the Meta webhook payload, or a
        list of them from the same sender (the webhook coalesces a burst into
        one turn so "hola" / "quiero cita" / "mañana en la tarde" get one
        answer instead of three half-answers).

        Bot pause is enforced upstream (webhook router, Redis key) — single
        source of truth; see whatsapp/coexistence.check_pause.
        """
        messages = message if isinstance(message, list) else [message]
        # Plain-value copy for the except handler: after a failed flush the
        # session is in pending-rollback and touching ORM attributes re-raises.
        office_id = str(office.id)
        trace = None
        try:
            # 1. Extract messages (transcribes voice notes)
            extracted = [await self.extract_message(m, office) for m in messages]
            whatsapp_id = extracted[0]["from"]
            message_text = "\n".join(e["text"] for e in extracted if e["text"])

            logger.info(
                "processing_message_v2",
                office_id=office_id,
                whatsapp_id=whatsapp_id,
                message_ids=[e["id"] for e in extracted],
            )
            trace = self.new_trace(
                office, "patient", whatsapp_id=whatsapp_id, user_text=message_text
            )

            # 2. Get or create session
            session = await self.session_store.get_session(whatsapp_id, office_id)
            conversation_obj: Optional[Conversation] = None

            if session:
                stmt = select(Conversation).where(Conversation.id == session.conversation_id)
                result = await db.execute(stmt)
                conversation_obj = result.scalar_one_or_none()
            if conversation_obj is None:
                conversation_obj = await self._get_or_create_conversation(db, office.id, whatsapp_id)
            if not session:
                session = SessionContext(
                    conversation_id=conversation_obj.id,
                    office_id=office.id,
                    whatsapp_id=whatsapp_id,
                    status="active",
                    claude_history=[],
                    collected_data={},
                )
            trace.conversation_id = conversation_obj.id

            # 3. Get or create patient
            patient = await self._get_or_create_patient(db, office.id, whatsapp_id)
            if patient:
                session.patient_id = patient.id
                conversation_obj.patient_id = patient.id

            # First contact is decided here, from the records, before this
            # message is saved: the model can't know about a chat from last
            # week once its session expired.
            is_first_contact = patient is None and not await self._has_prior_messages(
                db, conversation_obj.id
            )

            # 4. Save incoming messages (each one, for the dashboard history)
            for e in extracted:
                await self._save_incoming_message(db, office.id, whatsapp_id, e["text"], e["id"])

            # 5. Build system prompt and append the user turn to history
            is_returning = await is_returning_patient(db, office, session.patient_id)
            active_appt_id = (
                str(session.active_appointment_id)
                if session.active_appointment_id
                else None
            )
            session.state.drop_past_slots(now_mx())
            system_prompt = build_system_prompt(
                office,
                active_appointment_id=active_appt_id,
                is_returning_patient=is_returning,
                patient_name=patient.name if patient else None,
                session_status=session.status,
                is_first_contact=is_first_contact,
                reminder_rules=await self._reminder_rules(db, office.id),
                state_block=session.state.render(),
                schedules=await self._schedules(db, office.id),
            )
            session.claude_history = self.sanitize_history(session.claude_history)
            session.claude_history.append({"role": "user", "content": message_text})

            # 6. Tool-use loop on a per-turn working copy — the provider-specific
            # tool chain it accumulates is discarded after the turn; what the
            # tools established survives in session.state.
            tool_ctx = ToolContext(
                db=db,
                office=office,
                patient_id=session.patient_id,
                whatsapp_id=whatsapp_id,
                redis_client=self.session_store.redis_client,
                state=session.state,
            )
            working_messages = list(session.claude_history)
            try:
                response_text = await self.run_tool_loop(
                    system_prompt,
                    working_messages,
                    TOOL_DEFINITIONS,
                    execute_tool,
                    tool_ctx,
                    log_prefix="patient",
                    mutating_tools=MUTATING_TOOLS,
                    tool_claims=TOOL_CLAIMS,
                    # One call at a time: the booking flow is sequential by
                    # nature, and parallel writes are where duplicates came from.
                    parallel_tool_calls=False,
                    trace=trace,
                )
            except AIServiceError as e:
                # The model is unreachable. Anything a tool already wrote this
                # turn stands (it is committed below with the message), and the
                # patient hears something instead of silence.
                logger.error("patient_ai_unavailable", error=str(e), office_id=office_id)
                trace.outcome = "error"
                trace.error = str(e)
                response_text = self.AI_UNAVAILABLE_REPLY

            # Update patient_id if a tool created the patient
            if tool_ctx.patient_id and tool_ctx.patient_id != session.patient_id:
                session.patient_id = tool_ctx.patient_id

            # Release the pending-question state once it's been answered: the
            # appointment was confirmed/cancelled, or — while we were waiting on
            # an arrival report — the patient told us where they are.
            if session.active_appointment_id:
                appt = await db.get(Appointment, session.active_appointment_id)
                answered = appt is None or appt.status in ("confirmed", "cancelled")
                if (
                    not answered
                    and session.status == WAITING_ARRIVAL_STATUS
                    and appt.arrival_status is not None
                ):
                    answered = True
                if answered:
                    session.active_appointment_id = None
                    session.status = "active"

            # Fallback
            if not response_text or not response_text.strip():
                response_text = "Disculpa, no pude procesar tu mensaje. ¿Podrías repetirlo?"
                logger.warning("empty_response_fallback_v2", office_id=office_id)
            trace.reply = response_text

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
            await self.session_store.save_session(whatsapp_id, office_id, session)

            logger.info(
                "message_processed_v2",
                office_id=office_id,
                whatsapp_id=whatsapp_id,
            )

        except ConversationError:
            if trace is not None:
                trace.outcome = "error"
            raise
        except Exception as e:
            logger.error("conversation_processing_failed_v2", error=str(e), office_id=office_id)
            if trace is not None:
                trace.outcome = "error"
                trace.error = str(e)
            raise ConversationError(f"Failed to process conversation: {str(e)}") from e
        finally:
            if trace is not None:
                await persist_trace(trace)

    async def _has_prior_messages(self, db: AsyncSession, conversation_id) -> bool:
        result = await db.execute(
            select(Message.id).where(Message.conversation_id == conversation_id).limit(1)
        )
        return result.scalars().first() is not None

    async def _schedules(self, db: AsyncSession, office_id) -> list[AvailabilitySchedule]:
        """The office's weekly hours, for the prompt's HORARIO DE ATENCIÓN."""
        result = await db.execute(
            select(AvailabilitySchedule).where(
                (AvailabilitySchedule.office_id == office_id)
                & (AvailabilitySchedule.is_active == True)  # noqa: E712
            )
        )
        return list(result.scalars().all())

    async def _reminder_rules(self, db: AsyncSession, office_id) -> list[ReminderRule]:
        """The office's reminder rules, for the prompt's capabilities section."""
        result = await db.execute(
            select(ReminderRule).where(ReminderRule.office_id == office_id)
        )
        rules = list(result.scalars().all())
        if rules:
            return rules
        # Offices created before per-office rules existed run on the defaults.
        return [
            ReminderRule(reminder_type=t.value, offset_minutes=o, enabled=True)
            for t, o in DEFAULT_REMINDER_RULES
        ]

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
        """Find the patient behind an incoming WhatsApp id.

        Matches on every equivalent form of the number, not just the raw Meta
        id. A patient the office registered by phone — someone booked for by a
        relative, or added from the dashboard — is stored as "+52…" or as the
        10 digits, so an exact match on the inbound "521…" missed them and the
        bot answered a known patient with "no tienes citas".
        """
        try:
            variants = phone_match_variants(whatsapp_id)
        except ValueError:
            variants = [whatsapp_id]
        if whatsapp_id not in variants:
            variants.append(whatsapp_id)

        stmt = select(Patient).where(
            (Patient.office_id == office_id)
            & (Patient.whatsapp_id.in_(variants) | Patient.phone.in_(variants))
        ).limit(1)
        result = await db.execute(stmt)
        return result.scalars().first()

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
