"""Base AI service with shared logic for intent detection and response generation."""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional, Union

from app.utils.logger import get_logger
from app.core.exceptions import AIServiceError

logger = get_logger(__name__)

# A system prompt is either a plain string or a (static, dynamic) pair. The
# static part is byte-identical across a conversation's turns, so providers
# can cache it as a prefix (OpenAI automatic caching needs a stable prefix;
# AnthropicService marks it with cache_control). The dynamic part carries
# per-turn context (current date/time, pending confirmations/urgencies).
SystemPrompt = Union[str, tuple]


def join_system_prompt(system_prompt: SystemPrompt) -> str:
    """Flatten a (static, dynamic) system prompt into a single string."""
    if isinstance(system_prompt, tuple):
        return "\n\n".join(part for part in system_prompt if part)
    return system_prompt


@dataclass
class ToolCall:
    """A tool call requested by the LLM."""
    id: str
    name: str
    arguments: dict


@dataclass
class ChatResponse:
    """Response from an LLM that may include tool calls."""
    text: Optional[str]
    tool_calls: list[ToolCall] = field(default_factory=list)
    stop_reason: str = "end_turn"
    raw_message: Any = None  # Provider-specific message for appending to history


class BaseAIService(ABC):
    """
    Abstract base class for AI services.

    Subclasses implement _raw_chat() and _raw_chat_with_tools() with their
    specific SDK. Retry logic, intent detection, and response generation
    are shared here.
    """

    max_retries: int = 2

    @abstractmethod
    async def _raw_chat(
        self,
        system_prompt: str,
        messages: list[dict],
        max_tokens: int,
        temperature: float,
    ) -> str:
        """SDK-specific chat call. No retry logic — just the API call."""
        ...

    @abstractmethod
    async def _raw_chat_with_tools(
        self,
        system_prompt: SystemPrompt,
        messages: list[dict],
        tools: list[dict],
        max_tokens: int,
        temperature: float,
        tool_choice: Optional[str] = None,
    ) -> ChatResponse:
        """SDK-specific chat call with tool definitions. No retry logic.

        tool_choice="none" forces a text-only reply (used to close a turn
        gracefully when the tool-iteration budget is exhausted).
        """
        ...

    @abstractmethod
    def build_tool_result_messages(
        self,
        assistant_message: Any,
        tool_results: list[dict],
    ) -> list[dict]:
        """
        Build provider-specific messages for tool results.

        Args:
            assistant_message: The raw_message from ChatResponse (provider-specific)
            tool_results: List of dicts with 'tool_call_id' and 'result' keys

        Returns:
            List of messages to append to history (provider-specific format)
        """
        ...

    async def _with_retries(self, fn, operation_name: str):
        """Execute an async function with exponential backoff retries."""
        for attempt in range(self.max_retries + 1):
            try:
                return await fn()
            except AIServiceError:
                raise
            except Exception as e:
                logger.warning(
                    f"{operation_name}_error",
                    error=str(e),
                    attempt=attempt + 1,
                    max_retries=self.max_retries,
                )
                if attempt < self.max_retries:
                    await asyncio.sleep(2 ** attempt)
                    continue
                logger.error(
                    f"{operation_name}_failed_after_retries",
                    error=str(e),
                    total_attempts=attempt + 1,
                )
                raise AIServiceError(
                    f"LLM API failed after {self.max_retries + 1} attempts: {str(e)}"
                ) from e

    async def chat(
        self,
        system_prompt: str,
        messages: list[dict[str, str]],
        max_tokens: int = 512,
        temperature: float = 0.7,
    ) -> str:
        """Send a conversation to the LLM and get a text response."""
        return await self._with_retries(
            lambda: self._raw_chat(system_prompt, messages, max_tokens, temperature),
            "llm_chat",
        )

    async def chat_with_tools(
        self,
        system_prompt: SystemPrompt,
        messages: list[dict],
        tools: list[dict],
        max_tokens: int = 4096,
        temperature: float = 0.5,
        tool_choice: Optional[str] = None,
    ) -> ChatResponse:
        """Send a conversation with tool definitions and get a response that may include tool calls."""
        return await self._with_retries(
            lambda: self._raw_chat_with_tools(
                system_prompt, messages, tools, max_tokens, temperature, tool_choice
            ),
            "llm_chat_with_tools",
        )
