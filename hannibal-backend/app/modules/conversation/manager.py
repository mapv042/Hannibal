"""Main orchestrator for conversation processing and intent-based actions."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any, Optional
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.utils.logger import get_logger
from app.core.constants import Intent, MX_TIMEZONE
from app.core.exceptions import ConversationError
from app.db.models import Office, Patient, Conversation, Message, Appointment
from app.modules.ai.claude_service import ClaudeService
from app.modules.ai.intent_detector import detect_intent
from app.modules.ai.response_gen import generate_response
from app.modules.conversation.session_store import SessionStore
from app.modules.conversation.schemas import SessionContext
from app.modules.whatsapp.meta_client import MetaCloudClient
from app.modules.google_calendar.service import get_freebusy, create_calendar_event
from app.modules.google_calendar.sync import cancel_appointment_in_calendar

if TYPE_CHECKING:
    from redis.asyncio import Redis

logger = get_logger(__name__)


class ConversationManager:
    """
    Main orchestrator for WhatsApp conversation processing.

    Manages the complete flow:
    1. Extract message from webhook
    2. Check pause/coexistence status
    3. Get or create session
    4. Detect intent
    5. Execute intent-specific action
    6. Generate response
    7. Send via Meta Cloud API
    8. Save to database
    9. Update session
    """

    def __init__(
        self,
        session_store: SessionStore,
        meta_client: MetaCloudClient,
        claude_service: ClaudeService | None = None,
    ):
        """
        Initialize conversation manager.

        Args:
            session_store: Redis session store
            meta_client: Meta Cloud API client for sending messages
            claude_service: Claude service instance (creates new if None)
        """
        self.session_store = session_store
        self.meta_client = meta_client
        self.claude_service = claude_service or ClaudeService()

    async def process(
        self,
        office: Office,
        payload: dict[str, Any],
        db: AsyncSession,
    ) -> None:
        """
        Process incoming WhatsApp message and generate response.

        Main entry point that orchestrates the entire conversation flow.

        Args:
            office: Office instance
            payload: WhatsApp webhook payload
            db: Database session for queries and saves

        Raises:
            ConversationError: If processing fails critically
        """
        try:
            # 1. Extract message from payload
            message_data = self._extract_message_from_payload(payload)
            whatsapp_id = message_data["from"]
            message_text = message_data["text"]
            message_id = message_data["id"]
            timestamp = message_data["timestamp"]

            logger.info(
                "processing_message",
                office_id=str(office.id),
                whatsapp_id=whatsapp_id,
                message_id=message_id,
            )

            # 2. Check if bot is paused
            if office.bot_paused_until:
                now = datetime.now(tz=ZoneInfo("UTC"))
                if now < office.bot_paused_until:
                    logger.info(
                        "bot_paused",
                        office_id=str(office.id),
                        paused_until=office.bot_paused_until,
                    )
                    # Still save the message but don't process
                    await self._save_incoming_message(
                        db, office.id, whatsapp_id, message_text, message_id
                    )
                    return

            # 3. Get or create conversation session
            session = await self.session_store.get_session(
                whatsapp_id, str(office.id)
            )

            conversation_obj: Optional[Conversation] = None
            if session:
                # Retrieve existing conversation record
                stmt = select(Conversation).where(
                    Conversation.id == session.conversation_id
                )
                result = await db.execute(stmt)
                conversation_obj = result.scalar_one_or_none()
            else:
                # Create new conversation session
                conversation_obj = await self._get_or_create_conversation(
                    db, office.id, whatsapp_id
                )
                session = SessionContext(
                    conversation_id=conversation_obj.id,
                    office_id=office.id,
                    whatsapp_id=whatsapp_id,
                    status="active",
                    claude_history=[],
                    collected_data={},
                )

            # 4. Identify or create patient
            patient = await self._get_or_create_patient(
                db, office.id, whatsapp_id, session
            )
            if patient:
                session.patient_id = patient.id
                conversation_obj.patient_id = patient.id

            # 5. Save incoming message
            await self._save_incoming_message(
                db, office.id, whatsapp_id, message_text, message_id
            )

            # 6. Detect intent
            try:
                intent, intent_details = await detect_intent(
                    message=message_text,
                    history=session.claude_history,
                    claude_service=self.claude_service,
                )
            except Exception as e:
                logger.warning(
                    "intent_detection_fallback",
                    error=str(e),
                    office_id=str(office.id),
                )
                intent = Intent.OTHER
                intent_details = {"confidence": 0.0, "extracted_data": {}, "explanation": "fallback"}

            session.current_intent = intent.value

            logger.info(
                "intent_detected_in_manager",
                intent=intent.value,
                confidence=intent_details.get("confidence"),
                office_id=str(office.id),
            )

            # 7. Execute action based on intent
            response_text = await self._handle_intent(
                office,
                intent,
                intent_details,
                session,
                message_text,
                db,
            )

            # Fallback for empty responses
            if not response_text or not response_text.strip():
                response_text = "Disculpa, no pude procesar tu mensaje. ¿Podrías repetirlo?"
                logger.warning("empty_response_fallback", office_id=str(office.id))

            # 8. Update conversation history
            session.claude_history.append(
                {"role": "user", "content": message_text}
            )
            session.claude_history.append(
                {"role": "assistant", "content": response_text}
            )

            # Keep only last 40 messages to avoid token bloat
            if len(session.claude_history) > 40:
                session.claude_history = session.claude_history[-40:]

            # 9. Send response via Meta API
            try:
                await self.meta_client.send_text_message(
                    phone_number_id=office.whatsapp_phone_id,
                    token=office.whatsapp_token,
                    to=whatsapp_id,
                    text=response_text,
                )
            except Exception as e:
                logger.error(
                    "failed_to_send_response",
                    error=str(e),
                    whatsapp_id=whatsapp_id,
                )
                # Continue anyway - we'll try to save what we can

            # 10. Save outgoing message
            await self._save_outgoing_message(
                db, conversation_obj.id, response_text
            )

            # 11. Update conversation state
            session.last_message_at = datetime.utcnow().isoformat()
            conversation_obj.status = session.status
            conversation_obj.current_intent = session.current_intent
            conversation_obj.last_message_at = datetime.now(tz=ZoneInfo("UTC"))

            await db.commit()

            # 12. Save session to Redis
            await self.session_store.save_session(
                whatsapp_id, str(office.id), session
            )

            logger.info(
                "message_processed_successfully",
                office_id=str(office.id),
                whatsapp_id=whatsapp_id,
                intent=intent.value,
            )

        except ConversationError:
            raise
        except Exception as e:
            logger.error(
                "conversation_processing_failed",
                error=str(e),
                office_id=str(office.id),
            )
            raise ConversationError(f"Failed to process conversation: {str(e)}") from e

    async def _handle_intent(
        self,
        office: Office,
        intent: Intent,
        intent_details: dict[str, Any],
        session: SessionContext,
        message_text: str,
        db: AsyncSession,
    ) -> str:
        """
        Handle intent-specific actions FIRST, then generate response
        that reflects what actually happened.
        """
        logger.debug("handling_intent", intent=intent.value)

        # Update session based on intent and execute actions
        data = intent_details.get("extracted_data", {})
        action_result = None  # Feedback for the LLM
        available_slots = []

        # If patient is in a waiting state, route responses to the correct intent
        # unless they explicitly start a completely new intent
        if (
            session.status in ("waiting_cancel_selection", "waiting_cancel_reason")
            and intent not in (Intent.SCHEDULE, Intent.GREETING, Intent.URGENT, Intent.RESCHEDULE)
        ):
            intent = Intent.CANCEL

        if (
            session.status in ("waiting_reschedule_selection", "waiting_reschedule_new_datetime")
            and intent not in (Intent.SCHEDULE, Intent.GREETING, Intent.URGENT, Intent.CANCEL)
        ):
            intent = Intent.RESCHEDULE

        if intent == Intent.SCHEDULE:
            session.status = "waiting_confirmation"
            if data.get("name"):
                session.collected_data["name"] = data["name"]
            if data.get("reason"):
                session.collected_data["reason"] = data["reason"]
            if data.get("proposed_date"):
                session.collected_data["proposed_date"] = data["proposed_date"]
            if data.get("proposed_time"):
                session.collected_data["proposed_time"] = data["proposed_time"]
            # Only fetch slots when we know which day the patient wants
            target_date = data.get("proposed_date") or session.collected_data.get("proposed_date")
            if target_date:
                available_slots = await self._get_available_slots(office, db, target_date=target_date)
                if not available_slots:
                    # No availability on requested day — clear date and inform LLM
                    session.collected_data.pop("proposed_date", None)
                    session.collected_data.pop("proposed_time", None)
                    action_result = (
                        f"SIN_DISPONIBILIDAD: No hay horarios disponibles para el {target_date}. "
                        "Informa al paciente que ese día no hay servicio y pregúntale si prefiere otro día."
                    )

        elif intent == Intent.CANCEL:
            # Multi-step cancellation flow (all critical steps are direct messages):
            # 1. Confirm which appointment → direct message
            # 2. Ask for reason → direct message
            # 3. Execute cancellation → direct message

            if session.status == "waiting_cancel_reason":
                # Step 3: Patient provided reason → execute cancellation
                appt_id = session.active_appointment_id
                if appt_id:
                    cancellation_reason = message_text
                    await self._cancel_appointment(db, appt_id, cancellation_reason)
                    try:
                        await cancel_appointment_in_calendar(appt_id, office.id, db)
                    except Exception as e:
                        logger.warning("cancel_calendar_failed", error=str(e))
                    stmt = select(Appointment).where(Appointment.id == appt_id)
                    result = await db.execute(stmt)
                    appt = result.scalar_one_or_none()
                    appt_str = self._format_appointment_for_display(appt) if appt else "cita"
                    session.active_appointment_id = None
                    session.status = "active"
                    return (
                        f"✅ Tu cita del {appt_str} ha sido cancelada exitosamente.\n\n"
                        "El horario queda disponible. Si necesitas agendar una nueva cita, "
                        "no dudes en escribirme. ¡Estoy para ayudarte!"
                    )
                else:
                    session.status = "active"
                    return "Disculpa, hubo un error al procesar la cancelación. ¿Podrías intentarlo de nuevo?"

            elif session.status == "waiting_cancel_selection":
                # Step 2: Patient selected which appointment (when multiple exist)
                appointments = await self._get_patient_upcoming_appointments(
                    db, session.patient_id, office.id
                )
                if appointments:
                    matched = self._match_appointment_from_message(
                        message_text, appointments
                    )
                    if matched:
                        session.active_appointment_id = matched.id
                        appt_str = self._format_appointment_for_display(matched)
                        session.status = "waiting_cancel_reason"
                        return (
                            f"Entendido, la cita del {appt_str}.\n\n"
                            "¿Podrías indicarme el motivo de la cancelación?"
                        )
                    else:
                        appt_lines = self._build_appointment_list(appointments)
                        return (
                            f"No pude identificar la cita. Estas son tus citas próximas:\n\n{appt_lines}\n\n"
                            "¿Cuál deseas cancelar? Puedes indicarme el número o la fecha."
                        )
                else:
                    session.status = "active"
                    return "No tienes citas próximas agendadas."

            else:
                # Step 1: Fresh cancel request → confirm which appointment
                if session.patient_id:
                    appointments = await self._get_patient_upcoming_appointments(
                        db, session.patient_id, office.id
                    )
                else:
                    appointments = []

                if len(appointments) == 1:
                    appt = appointments[0]
                    session.active_appointment_id = appt.id
                    appt_str = self._format_appointment_for_display(appt)
                    session.status = "waiting_cancel_reason"
                    return (
                        f"Tienes una cita el {appt_str}.\n\n"
                        "¿Podrías indicarme el motivo de la cancelación?"
                    )
                elif len(appointments) > 1:
                    appt_lines = self._build_appointment_list(appointments)
                    session.status = "waiting_cancel_selection"
                    return (
                        f"Tienes {len(appointments)} citas próximas:\n\n{appt_lines}\n\n"
                        "¿Cuál deseas cancelar?"
                    )
                else:
                    session.status = "active"
                    return "No tienes citas próximas agendadas. ¿Te gustaría agendar una nueva cita?"

        elif intent == Intent.RESCHEDULE:
            # Multi-step reschedule flow (direct messages for critical steps):
            # 1. Identify which appointment → direct message
            # 2. Ask for new date/time → direct message
            # 3. Cancel old + transition to scheduling flow

            if session.status == "waiting_reschedule_new_datetime":
                # Step 3: Patient provided new date/time → cancel old + start scheduling
                appt_id = session.active_appointment_id
                if appt_id:
                    stmt = select(Appointment).where(Appointment.id == appt_id)
                    result = await db.execute(stmt)
                    old_appt = result.scalar_one_or_none()
                    old_appt_str = self._format_appointment_for_display(old_appt) if old_appt else "cita anterior"

                    await self._cancel_appointment(db, appt_id, "Reagendada por el paciente")
                    try:
                        await cancel_appointment_in_calendar(appt_id, office.id, db)
                    except Exception as e:
                        logger.warning("reschedule_cancel_calendar_failed", error=str(e))

                    # Transition to scheduling flow
                    session.active_appointment_id = None
                    session.status = "waiting_confirmation"
                    session.collected_data.clear()
                    if old_appt and old_appt.consultation_reason:
                        session.collected_data["reason"] = old_appt.consultation_reason
                    if data.get("proposed_date"):
                        session.collected_data["proposed_date"] = data["proposed_date"]
                    if data.get("proposed_time"):
                        session.collected_data["proposed_time"] = data["proposed_time"]
                    if data.get("name"):
                        session.collected_data["name"] = data["name"]

                    target_date = data.get("proposed_date") or session.collected_data.get("proposed_date")
                    if target_date:
                        available_slots = await self._get_available_slots(office, db, target_date=target_date)
                    action_result = (
                        f"CITA_ANTERIOR_CANCELADA_PARA_REAGENDAR: La cita del {old_appt_str} fue cancelada. "
                        "El horario anterior queda libre. Ahora ayuda al paciente a elegir un nuevo horario."
                    )
                else:
                    session.status = "active"
                    return "Disculpa, hubo un error al procesar el reagendamiento. ¿Podrías intentarlo de nuevo?"

            elif session.status == "waiting_reschedule_selection":
                # Step 2: Patient selected which appointment (when multiple exist)
                appointments = await self._get_patient_upcoming_appointments(
                    db, session.patient_id, office.id
                )
                if appointments:
                    matched = self._match_appointment_from_message(
                        message_text, appointments
                    )
                    if matched:
                        session.active_appointment_id = matched.id
                        appt_str = self._format_appointment_for_display(matched)
                        session.status = "waiting_reschedule_new_datetime"
                        return (
                            f"Entendido, la cita del {appt_str}.\n\n"
                            "¿Para qué día y horario te gustaría cambiarla?"
                        )
                    else:
                        appt_lines = self._build_appointment_list(appointments)
                        return (
                            f"No pude identificar la cita. Estas son tus citas próximas:\n\n{appt_lines}\n\n"
                            "¿Cuál deseas reagendar? Puedes indicarme el número o la fecha."
                        )
                else:
                    session.status = "active"
                    return "No tienes citas próximas agendadas."

            else:
                # Step 1: Fresh reschedule request → identify appointment
                if session.patient_id:
                    appointments = await self._get_patient_upcoming_appointments(
                        db, session.patient_id, office.id
                    )
                else:
                    appointments = []

                if len(appointments) == 1:
                    appt = appointments[0]
                    session.active_appointment_id = appt.id
                    appt_str = self._format_appointment_for_display(appt)
                    session.status = "waiting_reschedule_new_datetime"
                    return (
                        f"Tienes una cita el {appt_str}.\n\n"
                        "¿Para qué día y horario te gustaría cambiarla?"
                    )
                elif len(appointments) > 1:
                    appt_lines = self._build_appointment_list(appointments)
                    session.status = "waiting_reschedule_selection"
                    return (
                        f"Tienes {len(appointments)} citas próximas:\n\n{appt_lines}\n\n"
                        "¿Cuál deseas reagendar?"
                    )
                else:
                    session.status = "active"
                    return "No tienes citas próximas agendadas. ¿Te gustaría agendar una nueva cita?"

        elif intent == Intent.CONFIRM:
            has_date = session.collected_data.get("proposed_date")
            has_time = session.collected_data.get("proposed_time")
            has_name = session.collected_data.get("name")
            has_reason = session.collected_data.get("reason")

            # Check all required fields before creating
            missing = []
            if not has_date:
                missing.append("fecha")
            if not has_time:
                missing.append("hora")
            if not has_name:
                missing.append("nombre completo")
            if not has_reason:
                missing.append("motivo de consulta")

            if missing:
                target_date = session.collected_data.get("proposed_date")
                if target_date:
                    available_slots = await self._get_available_slots(office, db, target_date=target_date)
                action_result = (
                    f"FALTAN_DATOS_PARA_AGENDAR: Aún necesitas preguntar al paciente: {', '.join(missing)}. "
                    "NO digas que la cita está agendada. Pide la información faltante de forma natural."
                )
            else:
                # All data collected — show summary and ask for explicit confirmation
                if not session.collected_data.get("summary_shown"):
                    # First CONFIRM: show summary directly (bypass LLM for consistency)
                    from datetime import date as date_cls
                    try:
                        d = date_cls.fromisoformat(has_date)
                        day_names = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
                        formatted_date = f"{day_names[d.weekday()]} {d.strftime('%d/%m/%Y')}"
                    except Exception:
                        formatted_date = has_date

                    summary_msg = (
                        f"📋 Estos son los datos de tu cita:\n\n"
                        f"👤 Nombre: {has_name}\n"
                        f"📅 Fecha: {formatted_date}\n"
                        f"🕐 Hora: {has_time}\n"
                        f"📝 Motivo: {has_reason}\n\n"
                        "¿Los datos son correctos? Responde *sí* para confirmar o indícame qué dato deseas cambiar."
                    )
                    session.collected_data["summary_shown"] = True
                    return summary_msg
                else:
                    # Second CONFIRM: patient confirmed the summary → create appointment
                    appointment_id = await self._create_appointment(
                        db, office.id, session.patient_id, session.collected_data
                    )
                    if appointment_id:
                        patient_name = session.collected_data.get("name", "")
                        date_str = session.collected_data.get("proposed_date", "")
                        time_str = session.collected_data.get("proposed_time", "")
                        reason_str = session.collected_data.get("reason", "")

                        from datetime import date as date_cls
                        try:
                            d = date_cls.fromisoformat(date_str)
                            day_names = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
                            formatted_date = f"{day_names[d.weekday()]} {d.strftime('%d/%m/%Y')}"
                        except Exception:
                            formatted_date = date_str

                        greeting = f" {patient_name}" if patient_name else ""
                        confirm_msg = (
                            f"✅ ¡Listo{greeting}! Tu cita ha sido agendada exitosamente.\n\n"
                            f"📅 Fecha: {formatted_date}\n"
                            f"🕐 Hora: {time_str}\n"
                            f"📋 Motivo: {reason_str}\n"
                            f"\n📍 {office.name}"
                            f"{(' - ' + office.address) if office.address else ''}\n\n"
                            "Si necesitas cancelar o cambiar tu cita, no dudes en escribirme. ¡Te esperamos!"
                        )

                        session.active_appointment_id = appointment_id
                        session.status = "active"
                        session.collected_data.clear()
                        return confirm_msg
                    else:
                        return "Disculpa, hubo un error al agendar tu cita. ¿Podrías intentarlo de nuevo?"

        elif intent == Intent.URGENT:
            logger.warning(
                "emergency_alert",
                office_id=str(office.id),
                whatsapp_id=session.whatsapp_id,
            )
            session.status = "emergency_alerted"

        elif intent in (Intent.QUESTION, Intent.GREETING, Intent.OTHER):
            session.status = "active"

        # Build extra context for the LLM so it knows what actually happened
        action_context = ""
        if action_result:
            action_context = f"\n\n[RESULTADO DE ACCIÓN DEL SISTEMA: {action_result}. Tu respuesta DEBE reflejar este resultado. NUNCA digas que una cita fue agendada si el resultado no dice CITA_CREADA_EXITOSAMENTE.]"

        # Fetch patient's upcoming appointments for Claude context
        patient_appt_strings = []
        if session.patient_id:
            try:
                upcoming = await self._get_patient_upcoming_appointments(
                    db, session.patient_id, office.id
                )
                for appt in upcoming:
                    appt_str = self._format_appointment_for_display(appt)
                    reason = appt.consultation_reason or "Consulta"
                    patient_appt_strings.append(f"{appt_str} - {reason}")
            except Exception as e:
                logger.warning("failed_to_fetch_patient_appointments", error=str(e))

        # Generate response with action feedback
        try:
            response = await generate_response(
                office=office,
                context=session.model_dump(),
                slots=available_slots,
                patient_appointments=patient_appt_strings or None,
                user_message=message_text + action_context,
                conversation_history=session.claude_history,
                claude_service=self.claude_service,
            )
        except Exception as e:
            logger.warning("response_generation_failed_fallback", error=str(e), intent=intent.value)
            response = ""

        # If LLM returned empty, generate a direct fallback based on intent
        if not response or not response.strip():
            logger.warning("empty_llm_response", intent=intent.value)
            if intent == Intent.SCHEDULE and available_slots:
                # Show available slots directly
                morning = [s for s in available_slots if self._is_morning_slot(s)]
                afternoon = [s for s in available_slots if not self._is_morning_slot(s)]
                response = "¡Claro! ¿Prefieres por la mañana o por la tarde?\n\n"
                if morning:
                    response += "🌅 *Mañana:*\n" + "\n".join(f"  • {s}" for s in morning) + "\n\n"
                if afternoon:
                    response += "🌇 *Tarde:*\n" + "\n".join(f"  • {s}" for s in afternoon)
                response += "\n\n¿Cuál horario te queda mejor?"
            elif intent == Intent.GREETING:
                response = f"¡Hola! Soy el asistente de {office.name}. ¿En qué puedo ayudarte? 😊"
            elif intent == Intent.QUESTION:
                response = f"Puedo ayudarte con información sobre {office.name}. ¿Qué necesitas saber?"

        return response

    def _extract_message_from_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        """
        Extract message details from webhook payload.

        Args:
            payload: WhatsApp webhook payload

        Returns:
            Dict with "from", "text", "id", "timestamp"

        Raises:
            ConversationError: If message format is invalid
        """
        try:
            entry = payload["entry"][0]
            changes = entry["changes"][0]
            value = changes["value"]
            messages = value.get("messages", [])

            if not messages:
                raise ValueError("No messages in payload")

            message = messages[0]

            if message.get("type") != "text":
                raise ValueError(f"Unsupported message type: {message.get('type')}")

            return {
                "from": message["from"],
                "text": message["text"]["body"],
                "id": message["id"],
                "timestamp": message["timestamp"],
            }

        except (KeyError, IndexError, ValueError) as e:
            logger.error(
                "failed_to_extract_message",
                error=str(e),
                payload_keys=list(payload.keys()),
            )
            raise ConversationError(f"Invalid message payload: {str(e)}") from e

    async def _get_or_create_conversation(
        self,
        db: AsyncSession,
        office_id: uuid.UUID,
        whatsapp_id: str,
    ) -> Conversation:
        """Get existing or create new conversation record."""
        stmt = select(Conversation).where(
            (Conversation.office_id == office_id)
            & (Conversation.whatsapp_id == whatsapp_id)
            & (Conversation.status != "archived")
        )
        result = await db.execute(stmt)
        conversation = result.scalar_one_or_none()

        if conversation:
            return conversation

        # Create new conversation
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
        self,
        db: AsyncSession,
        office_id: uuid.UUID,
        whatsapp_id: str,
        session: SessionContext,
    ) -> Optional[Patient]:
        """Get existing or create new patient record."""
        stmt = select(Patient).where(
            (Patient.office_id == office_id)
            & (Patient.whatsapp_id == whatsapp_id)
        )
        result = await db.execute(stmt)
        patient = result.scalar_one_or_none()

        if patient:
            # Update name if we just learned it
            if (
                session.collected_data.get("name")
                and not patient.name
            ):
                patient.name = session.collected_data["name"]
            return patient

        # Create new patient if we have a name
        name = session.collected_data.get("name")
        if name:
            patient = Patient(
                id=uuid.uuid4(),
                office_id=office_id,
                whatsapp_id=whatsapp_id,
                phone=whatsapp_id,
                name=name,
            )
            db.add(patient)
            await db.flush()
            return patient

        return None

    async def _get_available_slots(
        self, office: Office, db: AsyncSession, target_date: str | None = None,
    ) -> list[str]:
        """
        Get available appointment slots using AvailabilitySchedule from DB
        combined with Google Calendar freebusy to exclude busy times.

        Args:
            target_date: If provided (YYYY-MM-DD), only return slots for that specific date.
        """
        from datetime import timedelta, date as date_cls
        from app.db.models import AvailabilitySchedule

        now = datetime.now(tz=MX_TIMEZONE)

        # If a specific date is requested, only look at that day
        if target_date:
            try:
                specific_date = date_cls.fromisoformat(target_date)
                start_date = specific_date
                num_days = 1
                time_max = datetime.combine(specific_date, datetime.max.time()).replace(tzinfo=MX_TIMEZONE)
            except ValueError:
                # Invalid date format, fall back to 7 days
                start_date = now.date()
                num_days = 7
                time_max = now + timedelta(days=7)
        else:
            start_date = now.date()
            num_days = 7
            time_max = now + timedelta(days=7)

        # Get office availability schedules from DB
        stmt = select(AvailabilitySchedule).where(
            (AvailabilitySchedule.office_id == office.id)
            & (AvailabilitySchedule.is_active == True)
        )
        result = await db.execute(stmt)
        schedules = result.scalars().all()

        if not schedules:
            return ["No hay horarios configurados. Contacte al consultorio directamente."]

        # Build a map: day_of_week -> list of schedule configs
        # DB uses 0=Sun, 1=Mon, ..., 6=Sat
        schedule_by_day = {}
        for sched in schedules:
            schedule_by_day.setdefault(sched.day_of_week, []).append(sched)

        # Get busy periods from Google Calendar
        busy_ranges = []
        if office.google_calendar_token:
            busy_periods = await get_freebusy(office.id, now, time_max, db)
            for bp in busy_periods:
                start = datetime.fromisoformat(bp["start"].replace("Z", "+00:00")).astimezone(MX_TIMEZONE)
                end = datetime.fromisoformat(bp["end"].replace("Z", "+00:00")).astimezone(MX_TIMEZONE)
                busy_ranges.append((start, end))

        # Generate available slots
        available = []
        day_names = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
        current_day = now.date()

        for day_offset in range(num_days):
            check_date = start_date + timedelta(days=day_offset)
            # Convert Python weekday (0=Mon) to DB format (0=Sun, 1=Mon)
            db_day = (check_date.weekday() + 1) % 7

            day_schedules = schedule_by_day.get(db_day, [])
            if not day_schedules:
                continue

            for sched in day_schedules:
                slot_duration = timedelta(minutes=sched.appointment_duration_min)
                buffer = timedelta(minutes=sched.buffer_minutes)

                # Generate slots within this schedule's time range
                slot_time = datetime.combine(check_date, sched.start_time).replace(tzinfo=MX_TIMEZONE)
                end_time = datetime.combine(check_date, sched.end_time).replace(tzinfo=MX_TIMEZONE)

                while slot_time + slot_duration <= end_time:
                    slot_end = slot_time + slot_duration

                    # Skip past slots
                    if slot_time <= now:
                        slot_time = slot_time + slot_duration + buffer
                        continue

                    # Check if slot overlaps with any busy period
                    is_busy = any(
                        slot_time < busy_end and slot_end > busy_start
                        for busy_start, busy_end in busy_ranges
                    )

                    if not is_busy:
                        days_from_today = (check_date - current_day).days
                        if days_from_today == 0:
                            label = "Hoy"
                        elif days_from_today == 1:
                            label = "Mañana"
                        else:
                            label = f"{day_names[check_date.weekday()]} {check_date.strftime('%d/%m')}"
                        available.append(f"{label} {slot_time.strftime('%H:%M')}")

                    if len(available) >= 50:
                        return available

                    slot_time = slot_time + slot_duration + buffer

        return available

    @staticmethod
    def _is_morning_slot(slot: str) -> bool:
        """Check if a slot string is in the morning (before 12:00)."""
        parts = slot.rsplit(" ", 1)
        if len(parts) == 2 and ":" in parts[1]:
            try:
                hour = int(parts[1].split(":")[0])
                return hour < 12
            except ValueError:
                pass
        return True

    async def _get_patient_upcoming_appointments(
        self,
        db: AsyncSession,
        patient_id: uuid.UUID,
        office_id: uuid.UUID,
    ) -> list[Appointment]:
        """Get upcoming scheduled/confirmed appointments for a patient."""
        now = datetime.now(tz=MX_TIMEZONE)
        stmt = (
            select(Appointment)
            .where(
                (Appointment.patient_id == patient_id)
                & (Appointment.office_id == office_id)
                & (Appointment.status.in_(["scheduled", "confirmed"]))
                & (Appointment.start_datetime >= now)
            )
            .order_by(Appointment.start_datetime)
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    def _build_appointment_list(appointments: list[Appointment]) -> str:
        """Build a numbered list of appointments for display."""
        day_names = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
        lines = []
        for i, appt in enumerate(appointments, 1):
            dt = appt.start_datetime
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=MX_TIMEZONE)
            else:
                dt = dt.astimezone(MX_TIMEZONE)
            day_name = day_names[dt.weekday()]
            reason = appt.consultation_reason or "Consulta"
            lines.append(
                f"{i}) {day_name} {dt.strftime('%d/%m/%Y')} a las {dt.strftime('%H:%M')} - {reason}"
            )
        return "\n".join(lines)

    @staticmethod
    def _match_appointment_from_message(
        message: str, appointments: list[Appointment]
    ) -> Optional[Appointment]:
        """Try to match a patient's message to one of their appointments."""
        msg = message.lower().strip()

        # Match by number (e.g. "1", "la 1", "la primera", "la segunda")
        ordinals = {
            "1": 0, "primera": 0, "primer": 0, "uno": 0,
            "2": 0, "segunda": 1, "segundo": 1, "dos": 1,
            "3": 2, "tercera": 2, "tercer": 2, "tres": 2,
            "4": 3, "cuarta": 3, "cuarto": 3, "cuatro": 3,
            "5": 4, "quinta": 4, "quinto": 4, "cinco": 4,
        }
        # Fix: "2" should map to index 1, etc.
        ordinals["1"] = 0
        ordinals["2"] = 1
        ordinals["3"] = 2
        ordinals["4"] = 3
        ordinals["5"] = 4

        for word, idx in ordinals.items():
            if word in msg and idx < len(appointments):
                return appointments[idx]

        # Match by day name
        day_names_lower = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
        for appt in appointments:
            dt = appt.start_datetime
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=MX_TIMEZONE)
            else:
                dt = dt.astimezone(MX_TIMEZONE)
            day_name = day_names_lower[dt.weekday()]
            if day_name in msg:
                return appt
            # Match by date string (e.g. "31/03" or "31 de marzo")
            date_str = dt.strftime("%d/%m")
            if date_str in msg:
                return appt

        # If only one appointment and patient seems to confirm
        if len(appointments) == 1:
            confirm_words = ["si", "sí", "esa", "ok", "dale", "va", "correcto", "confirmo"]
            if any(w in msg for w in confirm_words):
                return appointments[0]

        return None

    @staticmethod
    def _format_appointment_for_display(appointment: Appointment) -> str:
        """Format an appointment as a human-readable string for WhatsApp."""
        day_names = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
        dt = appointment.start_datetime
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=MX_TIMEZONE)
        else:
            dt = dt.astimezone(MX_TIMEZONE)
        day_name = day_names[dt.weekday()]
        return f"{day_name} {dt.strftime('%d/%m/%Y')} a las {dt.strftime('%H:%M')}"

    async def _cancel_appointment(
        self,
        db: AsyncSession,
        appointment_id: uuid.UUID,
        cancellation_reason: str | None = None,
    ) -> None:
        """Cancel an appointment."""
        stmt = select(Appointment).where(Appointment.id == appointment_id)
        result = await db.execute(stmt)
        appointment = result.scalar_one_or_none()

        if appointment:
            appointment.status = "cancelled"
            appointment.cancelled_by = "patient"
            if cancellation_reason:
                appointment.cancellation_reason = cancellation_reason
            logger.info("appointment_cancelled", appointment_id=str(appointment_id))

    async def _create_appointment(
        self,
        db: AsyncSession,
        office_id: uuid.UUID,
        patient_id: Optional[uuid.UUID],
        data: dict[str, Any],
    ) -> Optional[uuid.UUID]:
        """
        Create an appointment in the DB and Google Calendar.
        """
        from datetime import timedelta

        proposed_date = data.get("proposed_date")
        proposed_time = data.get("proposed_time")
        reason = data.get("reason", "Consulta")
        patient_name = data.get("name", "Paciente")

        if not proposed_date or not proposed_time:
            logger.warning("appointment_missing_date_time", data=data)
            return None

        try:
            start_dt = datetime.strptime(
                f"{proposed_date} {proposed_time}", "%Y-%m-%d %H:%M"
            ).replace(tzinfo=MX_TIMEZONE)
            duration = timedelta(minutes=30)
            end_dt = start_dt + duration

            # Create Google Calendar event
            office = await db.get(Office, office_id)
            google_event_id = None
            if office and office.google_calendar_token:
                try:
                    google_event_id = await create_calendar_event(
                        office_id=office_id,
                        title=f"Cita: {patient_name}",
                        start_time=start_dt,
                        end_time=end_dt,
                        description=f"Motivo: {reason}\nAgendada por WhatsApp",
                        db=db,
                        color_id="9",  # Blue (scheduled) - changes to green (10) on attendance confirmation
                    )
                except Exception as e:
                    logger.error("google_calendar_create_failed", error=str(e))

            # Create DB record
            appointment_id = uuid.uuid4()
            appointment = Appointment(
                id=appointment_id,
                office_id=office_id,
                patient_id=patient_id,
                start_datetime=start_dt,
                end_datetime=end_dt,
                duration_minutes=30,
                consultation_reason=reason,
                status="scheduled",
                google_event_id=google_event_id,
            )
            db.add(appointment)
            await db.flush()

            logger.info(
                "appointment_created",
                appointment_id=str(appointment_id),
                office_id=str(office_id),
                google_event_id=google_event_id,
                start=start_dt.isoformat(),
            )

            return appointment_id

        except Exception as e:
            logger.error(
                "appointment_creation_failed",
                office_id=str(office_id),
                error=str(e),
                exc_info=True,
            )
            return None

    async def _save_incoming_message(
        self,
        db: AsyncSession,
        office_id: uuid.UUID,
        whatsapp_id: str,
        content: str,
        message_id: str,
    ) -> None:
        """Save incoming message to database."""
        # Get conversation
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
        self,
        db: AsyncSession,
        conversation_id: uuid.UUID,
        content: str,
    ) -> None:
        """Save outgoing message to database."""
        message = Message(
            id=uuid.uuid4(),
            conversation_id=conversation_id,
            content=content,
            type="text",
            direction="outgoing",
        )
        db.add(message)
        await db.flush()
