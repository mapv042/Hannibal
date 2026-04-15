"""AI service for LLM-powered features (Anthropic backend)."""

from __future__ import annotations

import asyncio

from anthropic import AsyncAnthropic

from app.config import settings
from app.utils.logger import get_logger
from app.core.exceptions import AIServiceError
from app.modules.ai.base_service import BaseAIService

logger = get_logger(__name__)


class AnthropicService(BaseAIService):
    """
    Service for LLM interactions via Anthropic async SDK.

    Uses Claude Haiku as the underlying model.
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
