"""Base AI service with shared logic for intent detection and response generation."""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import Any

from app.utils.logger import get_logger
from app.core.exceptions import AIServiceError
from app.modules.ai.prompts.intent import INTENT_DETECTION_SYSTEM_PROMPT

logger = get_logger(__name__)


class BaseAIService(ABC):
    """
    Abstract base class for AI services.

    Subclasses only need to implement chat() with their specific SDK.
    Intent detection and response generation logic is shared.
    """

    @abstractmethod
    async def chat(
        self,
        system_prompt: str,
        messages: list[dict[str, str]],
        max_tokens: int = 512,
        temperature: float = 0.7,
    ) -> str:
        """
        Send a conversation to the LLM and get a response.

        Args:
            system_prompt: System instructions
            messages: List of message dicts with "role" and "content" keys
            max_tokens: Maximum tokens in response
            temperature: Randomness of responses (0.0-1.0)

        Returns:
            LLM text response

        Raises:
            AIServiceError: If API call fails after retries
        """
        ...

    async def detect_intent(
        self,
        message: str,
        conversation_history: list[dict[str, str]] | None = None,
    ) -> dict[str, Any]:
        """
        Detect user intent from a message.

        Returns:
            Dict with "intent", "confidence", "extracted_data", "explanation"
        """
        from app.utils.dates import now_mx
        today = now_mx().date()

        system_prompt = INTENT_DETECTION_SYSTEM_PROMPT.format(
            today_date=today.isoformat(),
            current_year=today.year,
        )

        # Build structured messages from conversation history
        messages = []
        if conversation_history:
            messages = [msg for msg in conversation_history[-10:]]
        messages.append({"role": "user", "content": message})

        try:
            response_text = await self.chat(
                system_prompt=system_prompt,
                messages=messages,
                max_tokens=2000,
                temperature=0.2,
            )

            response_text = response_text.strip()
            if response_text.startswith("```"):
                response_text = response_text.split("```")[1]
                if response_text.startswith("json"):
                    response_text = response_text[4:]
                response_text = response_text.strip()

            intent_data = json.loads(response_text)

            logger.info(
                "intent_detected",
                intent=intent_data.get("intent"),
                confidence=intent_data.get("confidence"),
            )

            return intent_data

        except (json.JSONDecodeError, KeyError) as e:
            logger.error(
                "intent_detection_parse_error",
                error=str(e),
                response=response_text,
            )
            raise AIServiceError(
                f"Failed to parse intent detection response: {str(e)}"
            ) from e
        except AIServiceError:
            raise
        except Exception as e:
            logger.error("intent_detection_unexpected_error", error=str(e))
            raise AIServiceError(f"Unexpected error in intent detection: {str(e)}") from e

    async def generate_response(
        self,
        system_prompt: str,
        conversation_history: list[dict[str, str]],
        user_message: str,
        max_tokens: int = 4000,
    ) -> str:
        """
        Generate a conversational response to user's message.
        """
        messages = conversation_history.copy()
        messages.append({"role": "user", "content": user_message})

        if len(messages) > 20:
            messages = messages[-20:]

        try:
            response = await self.chat(
                system_prompt=system_prompt,
                messages=messages,
                max_tokens=max_tokens,
                temperature=0.5,
            )

            logger.info(
                "response_generated",
                response_length=len(response),
            )

            return response

        except AIServiceError:
            raise
        except Exception as e:
            logger.error("response_generation_error", error=str(e))
            raise AIServiceError(f"Failed to generate response: {str(e)}") from e
