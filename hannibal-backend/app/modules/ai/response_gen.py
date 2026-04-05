"""Response generation for conversational interactions."""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.utils.logger import get_logger
from app.core.exceptions import AIServiceError
from app.modules.ai.claude_service import ClaudeService
from app.modules.ai.prompts.base import build_system_prompt

if TYPE_CHECKING:
    from app.db.models import Office

logger = get_logger(__name__)

# WhatsApp message length limit
MAX_WHATSAPP_LENGTH = 4096
PRACTICAL_RESPONSE_LENGTH = 1000  # Keep responses concise for WhatsApp


async def generate_response(
    office: Office,
    context: dict,
    slots: list[str] | None = None,
    patient_appointments: list[str] | None = None,
    user_message: str = "",
    conversation_history: list[dict[str, str]] | None = None,
    claude_service: ClaudeService | None = None,
) -> str:
    """
    Generate a conversational response for user message.

    Args:
        office: Office instance with settings
        context: Session context with conversation state
        slots: Available appointment slots to offer
        user_message: Current user message
        conversation_history: Previous messages in conversation
        claude_service: ClaudeService instance (creates new if not provided)

    Returns:
        Response text optimized for WhatsApp

    Raises:
        AIServiceError: If response generation fails
    """
    if claude_service is None:
        claude_service = ClaudeService()

    if conversation_history is None:
        conversation_history = []

    try:
        # Build the system prompt with office context and available slots
        system_prompt = build_system_prompt(
            office=office,
            available_slots=slots,
            patient_appointments=patient_appointments,
        )

        # Generate response from Claude
        response = await claude_service.generate_response(
            system_prompt=system_prompt,
            conversation_history=conversation_history,
            user_message=user_message,
            max_tokens=4000,
        )

        # Post-process response
        response = _post_process_response(response)

        logger.info(
            "response_generated_successfully",
            office_id=str(office.id),
            response_length=len(response),
        )

        return response

    except AIServiceError:
        raise
    except Exception as e:
        logger.error(
            "response_generation_failed",
            error=str(e),
            office_id=str(office.id),
        )
        raise AIServiceError(f"Failed to generate response: {str(e)}") from e


def _post_process_response(response: str) -> str:
    """
    Post-process Claude's response for WhatsApp delivery.

    Handles:
    - Trimming excessive whitespace
    - Removing markdown formatting
    - Ensuring reasonable length
    - Validating content

    Args:
        response: Raw response from Claude

    Returns:
        Cleaned response suitable for WhatsApp
    """
    # Strip leading/trailing whitespace
    response = response.strip()

    # Remove markdown code blocks if present
    if response.startswith("```"):
        response = response.split("```")[1]
        if response.startswith(("json", "python", "text", "markdown")):
            response = response.split("\n", 1)[1] if "\n" in response else response
    if response.endswith("```"):
        response = response.rsplit("```", 1)[0]

    response = response.strip()

    # Enforce practical length for WhatsApp
    if len(response) > PRACTICAL_RESPONSE_LENGTH:
        # Try to cut at a sentence boundary
        truncated = response[:PRACTICAL_RESPONSE_LENGTH]
        last_period = truncated.rfind(".")
        last_newline = truncated.rfind("\n")

        cut_point = max(last_period, last_newline)
        if cut_point > PRACTICAL_RESPONSE_LENGTH - 200:
            response = truncated[:cut_point + 1]
        else:
            response = truncated + "..."

    # Ensure it doesn't exceed absolute WhatsApp limit
    if len(response) > MAX_WHATSAPP_LENGTH:
        response = response[:MAX_WHATSAPP_LENGTH - 3] + "..."

    # Remove excessive newlines (max 2 consecutive)
    while "\n\n\n" in response:
        response = response.replace("\n\n\n", "\n\n")

    return response


def _validate_response(response: str) -> bool:
    """
    Validate response content for safety and appropriateness.

    Args:
        response: Response text to validate

    Returns:
        True if response is valid, False otherwise
    """
    if not response or not isinstance(response, str):
        return False

    if len(response) > MAX_WHATSAPP_LENGTH:
        return False

    # Check for suspicious patterns
    suspicious_patterns = [
        "diagnóstico",  # No medical diagnosis
        "medicamento",  # No medication advice
        "droga",
        "cirugía",
    ]

    text_lower = response.lower()
    for pattern in suspicious_patterns:
        if pattern in text_lower:
            logger.warning("suspicious_pattern_detected", pattern=pattern)
            return False

    return True
