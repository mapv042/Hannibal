"""Intent detection and parsing from Claude responses."""

from __future__ import annotations

from typing import Any

from app.core.constants import Intent
from app.utils.logger import get_logger
from app.core.exceptions import IntentDetectionError
from app.modules.ai import get_ai_service

logger = get_logger(__name__)


async def detect_intent(
    message: str,
    history: list[dict[str, str]] | None = None,
    ai_service=None,
) -> tuple[Intent, dict[str, Any]]:
    """
    Detect user intent from message using LLM.

    Args:
        message: User's message text
        history: Conversation history for context
        ai_service: AI service instance (creates new via factory if not provided)

    Returns:
        Tuple of (Intent enum, extracted data dict)

    Raises:
        IntentDetectionError: If intent cannot be determined
    """
    if ai_service is None:
        ai_service = get_ai_service()

    try:
        intent_response = await ai_service.detect_intent(
            message=message,
            conversation_history=history,
        )

        # Parse the response
        intent_str = intent_response.get("intent", "OTHER").upper()
        confidence = intent_response.get("confidence", 0.0)
        extracted_data = intent_response.get("extracted_data", {})
        explanation = intent_response.get("explanation", "")

        # Map to Intent enum
        try:
            intent = Intent(intent_str)
        except ValueError:
            logger.warning(
                "invalid_intent_value",
                intent_str=intent_str,
                defaulting_to="OTHER",
            )
            intent = Intent.OTHER

        logger.info(
            "intent_detection_complete",
            intent=intent.value,
            confidence=confidence,
            extracted_data=extracted_data,
        )

        return intent, {
            "confidence": confidence,
            "extracted_data": extracted_data,
            "explanation": explanation,
        }

    except Exception as e:
        logger.error(
            "intent_detection_failed",
            error=str(e),
            message_preview=message[:100],
        )
        raise IntentDetectionError(f"Failed to detect intent: {str(e)}") from e


def _normalize_extracted_data(data: dict[str, Any]) -> dict[str, Any]:
    """
    Normalize and validate extracted data.

    Handles edge cases like empty strings, None values, ambiguous data.

    Args:
        data: Raw extracted data from Claude

    Returns:
        Normalized data dict
    """
    normalized = {}

    # Patient name
    name = data.get("name")
    if name and isinstance(name, str) and name.strip():
        normalized["name"] = name.strip()
    else:
        normalized["name"] = None

    # Reason for consultation
    reason = data.get("reason")
    if reason and isinstance(reason, str) and reason.strip():
        normalized["reason"] = reason.strip()
    else:
        normalized["reason"] = None

    # Proposed date
    proposed_date = data.get("proposed_date")
    if proposed_date and isinstance(proposed_date, str) and proposed_date.strip():
        # Validate date format YYYY-MM-DD
        try:
            from datetime import datetime

            datetime.strptime(proposed_date.strip(), "%Y-%m-%d")
            normalized["proposed_date"] = proposed_date.strip()
        except ValueError:
            logger.warning("invalid_date_format", proposed_date=proposed_date)
            normalized["proposed_date"] = None
    else:
        normalized["proposed_date"] = None

    # Proposed time
    proposed_time = data.get("proposed_time")
    if proposed_time and isinstance(proposed_time, str) and proposed_time.strip():
        # Validate time format HH:MM
        try:
            from datetime import datetime

            datetime.strptime(proposed_time.strip(), "%H:%M")
            normalized["proposed_time"] = proposed_time.strip()
        except ValueError:
            logger.warning("invalid_time_format", proposed_time=proposed_time)
            normalized["proposed_time"] = None
    else:
        normalized["proposed_time"] = None

    # Appointment number
    appointment_number = data.get("appointment_number")
    if appointment_number and isinstance(appointment_number, str) and appointment_number.strip():
        normalized["appointment_number"] = appointment_number.strip()
    else:
        normalized["appointment_number"] = None

    return normalized
