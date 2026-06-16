"""AI service for LLM-powered features (OpenAI backend)."""

from __future__ import annotations

import json
from typing import Any

from openai import AsyncOpenAI

from app.config import settings
from app.utils.logger import get_logger
from app.modules.ai.base_service import BaseAIService, ChatResponse, ToolCall

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
        self.model = settings.open_ai_model

    async def _raw_chat(
        self,
        system_prompt: str,
        messages: list[dict],
        max_tokens: int,
        temperature: float,
    ) -> str:
        openai_messages = [{"role": "system", "content": system_prompt}]
        openai_messages.extend(messages)

        logger.debug(
            "llm_chat_request",
            model=self.model,
            messages_count=len(messages),
            max_tokens=max_tokens,
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

    async def _raw_chat_with_tools(
        self,
        system_prompt: str,
        messages: list[dict],
        tools: list[dict],
        max_tokens: int,
        temperature: float,
    ) -> ChatResponse:
        openai_messages = [{"role": "system", "content": system_prompt}]
        openai_messages.extend(messages)

        # Convert tools to OpenAI function-calling format
        openai_tools = [
            {
                "type": "function",
                "function": {
                    "name": tool["name"],
                    "description": tool.get("description", ""),
                    "parameters": tool.get("input_schema", {}),
                },
            }
            for tool in tools
        ]

        logger.debug(
            "llm_chat_with_tools_request",
            model=self.model,
            messages_count=len(messages),
            tools_count=len(tools),
            max_tokens=max_tokens,
        )

        response = await self.client.chat.completions.create(
            model=self.model,
            messages=openai_messages,
            tools=openai_tools,
            max_completion_tokens=max_tokens,
        )

        choice = response.choices[0]
        message = choice.message

        logger.info(
            "llm_chat_with_tools_success",
            tokens_input=response.usage.prompt_tokens if response.usage else 0,
            tokens_output=response.usage.completion_tokens if response.usage else 0,
            finish_reason=choice.finish_reason,
        )

        # Parse tool calls
        tool_calls = []
        if message.tool_calls:
            for tc in message.tool_calls:
                tool_calls.append(ToolCall(
                    id=tc.id,
                    name=tc.function.name,
                    arguments=json.loads(tc.function.arguments),
                ))

        # Build raw message for history (OpenAI format)
        raw = {"role": "assistant", "content": message.content}
        if message.tool_calls:
            raw["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                }
                for tc in message.tool_calls
            ]

        return ChatResponse(
            text=message.content,
            tool_calls=tool_calls,
            stop_reason=choice.finish_reason or "stop",
            raw_message=raw,
        )

    def build_tool_result_messages(
        self,
        assistant_message: Any,
        tool_results: list[dict],
    ) -> list[dict]:
        """
        Build OpenAI-format messages for tool results.

        OpenAI expects:
          [assistant_message, {"role": "tool", "tool_call_id": ..., "content": ...}, ...]
        """
        result_messages = [assistant_message]
        for result in tool_results:
            content = result["result"]
            if not isinstance(content, str):
                content = json.dumps(content, ensure_ascii=False)
            result_messages.append({
                "role": "tool",
                "tool_call_id": result["tool_call_id"],
                "content": content,
            })
        return result_messages
