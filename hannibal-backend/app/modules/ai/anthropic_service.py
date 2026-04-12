"""AI service for LLM-powered features (Anthropic backend)."""

from __future__ import annotations

import json
import asyncio
from typing import Any

from anthropic import AsyncAnthropic

from app.config import settings
from app.utils.logger import get_logger
from app.core.exceptions import AIServiceError
from app.modules.ai.prompts.intent import INTENT_DETECTION_PROMPT

logger = get_logger(__name__)


class AnthropicService:
    """
    Service for LLM interactions via Anthropic async SDK.

    Uses Claude Haiku as the underlying model.
    Implements the same interface as OpenAIService so they
    can be swapped via the ai_provider config.
    """

    def __init__(self, timeout: int = 30, max_retries: int = 2):
        self.client = AsyncAnthropic(
            api_key=settings.anthropic_api_key,
            timeout=timeout,
        )
        self.max_retries = max_retries
        self.model = "claude-haiku-4-5-20251001"

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
        for attempt in range(self.max_retries + 1):
            try:
                logger.debug(
                    "llm_chat_request",
                    model=self.model,
                    messages_count=len(messages),
                    max_tokens=max_tokens,
                    attempt=attempt + 1,
                )

                response = await self.client.messages.create(
                    model=self.model,
                    system=system_prompt,
                    messages=messages,
                    max_tokens=max_tokens,
                    temperature=temperature,
                )

                content = response.content[0].text if response.content else ""

                logger.info(
                    "llm_chat_success",
                    tokens_input=response.usage.input_tokens,
                    tokens_output=response.usage.output_tokens,
                    finish_reason=response.stop_reason,
                )

                return content

            except Exception as e:
                logger.warning(
                    "llm_chat_error",
                    error=str(e),
                    attempt=attempt + 1,
                    max_retries=self.max_retries,
                )

                if attempt < self.max_retries:
                    await asyncio.sleep(2 ** attempt)
                    continue

                logger.error(
                    "llm_chat_failed_after_retries",
                    error=str(e),
                    total_attempts=attempt + 1,
                )
                raise AIServiceError(
                    f"LLM API failed after {self.max_retries + 1} attempts: {str(e)}"
                ) from e

        raise AIServiceError("Unexpected error in chat method")

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
        history_text = ""
        if conversation_history:
            history_text = "\n".join(
                f"{msg.get('role', '').upper()}: {msg.get('content', '')}"
                for msg in conversation_history[-10:]
            )

        from app.utils.dates import now_mx
        today = now_mx().date()

        prompt = INTENT_DETECTION_PROMPT.format(
            today_date=today.isoformat(),
            current_year=today.year,
            conversation_history=history_text or "Sin historial previo",
            user_message=message,
        )

        try:
            response_text = await self.chat(
                system_prompt="Eres un experto en procesamiento de lenguaje natural. Responde SOLO con JSON valido, sin explicaciones adicionales.",
                messages=[{"role": "user", "content": prompt}],
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
                temperature=0.8,
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
