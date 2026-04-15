"""AI service for LLM-powered features (OpenAI backend)."""

from __future__ import annotations

import asyncio

from openai import AsyncOpenAI

from app.config import settings
from app.utils.logger import get_logger
from app.core.exceptions import AIServiceError
from app.modules.ai.base_service import BaseAIService

logger = get_logger(__name__)


class OpenAIService(BaseAIService):
    """
    Service for LLM interactions via OpenAI async SDK.

    Uses GPT-4.1-mini as the underlying model.
    """

    def __init__(self, timeout: int = 30, max_retries: int = 2):
        self.client = AsyncOpenAI(
            api_key=settings.open_ai_key,
            timeout=timeout,
        )
        self.max_retries = max_retries
        self.model = "gpt-4.1-mini"

    async def chat(
        self,
        system_prompt: str,
        messages: list[dict[str, str]],
        max_tokens: int = 512,
        temperature: float = 0.7,
    ) -> str:
        # Build OpenAI messages format
        openai_messages = [{"role": "system", "content": system_prompt}]
        openai_messages.extend(messages)

        for attempt in range(self.max_retries + 1):
            try:
                logger.debug(
                    "llm_chat_request",
                    model=self.model,
                    messages_count=len(messages),
                    max_tokens=max_tokens,
                    attempt=attempt + 1,
                )

                response = await self.client.chat.completions.create(
                    model=self.model,
                    messages=openai_messages,
                    max_completion_tokens=max_tokens,
                )

                content = response.choices[0].message.content or ""

                logger.info(
                    "llm_chat_success",
                    tokens_input=response.usage.prompt_tokens if response.usage else 0,
                    tokens_output=response.usage.completion_tokens if response.usage else 0,
                    finish_reason=response.choices[0].finish_reason,
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
