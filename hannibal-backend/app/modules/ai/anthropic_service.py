"""AI service for LLM-powered features (Anthropic backend)."""

from __future__ import annotations

import json
from typing import Any

from anthropic import AsyncAnthropic

from app.config import settings
from app.utils.logger import get_logger
from app.modules.ai.base_service import BaseAIService, ChatResponse, ToolCall

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
        self.model = settings.anthropic_ai_model

    async def _raw_chat(
        self,
        system_prompt: str,
        messages: list[dict],
        max_tokens: int,
        temperature: float,
    ) -> str:
        logger.debug(
            "llm_chat_request",
            model=self.model,
            messages_count=len(messages),
            max_tokens=max_tokens,
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

    async def _raw_chat_with_tools(
        self,
        system_prompt: str,
        messages: list[dict],
        tools: list[dict],
        max_tokens: int,
        temperature: float,
    ) -> ChatResponse:
        logger.debug(
            "llm_chat_with_tools_request",
            model=self.model,
            messages_count=len(messages),
            tools_count=len(tools),
            max_tokens=max_tokens,
        )

        response = await self.client.messages.create(
            model=self.model,
            system=system_prompt,
            messages=messages,
            tools=tools,
            max_tokens=max_tokens,
            temperature=temperature,
        )

        logger.info(
            "llm_chat_with_tools_success",
            tokens_input=response.usage.input_tokens,
            tokens_output=response.usage.output_tokens,
            stop_reason=response.stop_reason,
        )

        # Parse response content blocks
        text_parts = []
        tool_calls = []

        for block in response.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                tool_calls.append(ToolCall(
                    id=block.id,
                    name=block.name,
                    arguments=block.input,
                ))

        return ChatResponse(
            text="\n".join(text_parts) if text_parts else None,
            tool_calls=tool_calls,
            stop_reason=response.stop_reason,
            # Store the raw content blocks for history (Anthropic format)
            raw_message={"role": "assistant", "content": [b.model_dump() for b in response.content]},
        )

    def build_tool_result_messages(
        self,
        assistant_message: Any,
        tool_results: list[dict],
    ) -> list[dict]:
        """
        Build Anthropic-format messages for tool results.

        Anthropic expects:
          [assistant_message, {"role": "user", "content": [tool_result_blocks...]}]
        """
        tool_result_blocks = []
        for result in tool_results:
            tool_result_blocks.append({
                "type": "tool_result",
                "tool_use_id": result["tool_call_id"],
                "content": json.dumps(result["result"], ensure_ascii=False) if not isinstance(result["result"], str) else result["result"],
            })

        return [
            assistant_message,
            {"role": "user", "content": tool_result_blocks},
        ]
