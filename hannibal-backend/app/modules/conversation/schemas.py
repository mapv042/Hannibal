"""Pydantic schemas for conversation session state."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class SessionContext(BaseModel):
    """
    Represents the session state stored in Redis for a WhatsApp conversation.

    Tracks conversation history, extracted data, and flow state.
    """

    # Conversation identifiers
    conversation_id: UUID = Field(..., description="Database conversation record ID")
    office_id: UUID = Field(..., description="Office this conversation belongs to")
    patient_id: Optional[UUID] = Field(
        None, description="Patient ID if identified, else None"
    )
    whatsapp_id: str = Field(..., description="WhatsApp sender ID (phone number)")

    # Conversation state
    status: str = Field(
        default="active",
        description="Current state: active, waiting_date, waiting_time, waiting_confirmation, etc.",
    )
    current_intent: Optional[str] = Field(
        None, description="Last detected intent: SCHEDULE, CANCEL, RESCHEDULE, CONFIRM, etc."
    )

    # Collected data for appointment booking
    collected_data: dict[str, Any] = Field(
        default_factory=dict,
        description="Extracted patient data: name, reason, proposed_date, proposed_time, etc.",
    )

    # Claude conversation history
    claude_history: list[dict[str, str]] = Field(
        default_factory=list,
        description="Conversation history for Claude context (role/content pairs)",
    )

    # Control flags
    bot_paused: bool = Field(
        default=False,
        description="Whether bot is paused (doctor took over)",
    )

    # Activity tracking
    last_message_at: str = Field(
        default_factory=lambda: datetime.utcnow().isoformat(),
        description="ISO timestamp of last message",
    )

    # Appointment tracking (if applicable)
    active_appointment_id: Optional[UUID] = Field(
        None, description="ID of active appointment being discussed"
    )

    class Config:
        """Pydantic config."""

        json_schema_extra = {
            "example": {
                "conversation_id": "550e8400-e29b-41d4-a716-446655440000",
                "office_id": "550e8400-e29b-41d4-a716-446655440001",
                "patient_id": None,
                "whatsapp_id": "5215551234567",
                "status": "active",
                "current_intent": "SCHEDULE",
                "collected_data": {
                    "name": "Juan Pérez",
                    "reason": "Revisión general",
                    "proposed_date": "2024-03-25",
                    "proposed_time": "14:30",
                },
                "claude_history": [
                    {
                        "role": "user",
                        "content": "Hola, quiero agendar una cita",
                    },
                    {
                        "role": "assistant",
                        "content": "¡Hola! Me encantaría ayudarte. ¿Cuál es el motivo de tu consulta?",
                    },
                ],
                "bot_paused": False,
                "last_message_at": "2024-03-23T15:30:45.123456",
                "active_appointment_id": None,
            }
        }
