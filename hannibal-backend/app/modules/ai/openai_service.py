"""AI service for LLM-powered features (OpenAI backend)."""

from __future__ import annotations

import json
from typing import Any

from openai import AsyncOpenAI

from app.config import settings
from app.utils.logger import get_logger
from app.modules.ai.base_service import (
    BaseAIService,
    ChatResponse,
    SystemPrompt,
    ToolCall,
    join_system_prompt,
)

logger = get_logger(__name__)

# OpenAI's per-model parameter support is not discoverable at runtime, so the
# matrix lives here. Reasoning-first models (gpt-5.6+, o-series) take
# `reasoning_effort` and reject `temperature`/`top_p` outright — the presence of
# the parameter is the error, not its value. Older models (gpt-5.4-mini,
# gpt-4.1-mini) are the exact reverse: they take `temperature` and 400 on
# `reasoning_effort`. Sending the wrong one is a hard 400, so this drives both.
#
# On /v1/chat/completions the reasoning-first models also reject function tools
# unless `reasoning_effort` is "none" — OpenAI confirmed (2026-09-07) that this
# is a deliberate limitation, not a bug, to push tool users to /v1/responses.
# Since the whole conversation flow is tool-use, "none" is the only value that
# works here.
REASONING_FIRST_PREFIXES = ("gpt-5.6", "gpt-6", "o1", "o3", "o4")


def is_reasoning_first_model(model: str) -> bool:
    """True if the model takes `reasoning_effort` and refuses `temperature`."""
    return model.startswith(REASONING_FIRST_PREFIXES)


class OpenAIService(BaseAIService):
    """
    Service for LLM interactions via OpenAI async SDK.

    The model comes from OPEN_AI_MODEL.
    """

    def __init__(
        self,
        timeout: int = 30,
        max_retries: int = 2,
        model: str | None = None,
        reasoning_effort: str | None = None,
    ):
        self.client = AsyncOpenAI(
            api_key=settings.open_ai_key,
            timeout=timeout,
        )
        self.max_retries = max_retries
        self.model = model or settings.open_ai_model
        self.is_reasoning_first = is_reasoning_first_model(self.model)
        # On this endpoint a reasoning-first model rejects function tools
        # unless the effort is "none", so anything else would 400 the whole
        # conversation. The factory routes those models to /v1/responses for
        # exactly this reason; the parameter is accepted here only so both
        # services have the same shape.
        self.effort = (
            reasoning_effort
            if reasoning_effort is not None
            else settings.open_ai_reasoning_effort
        )

    def _apply_sampling_params(self, request_kwargs: dict, temperature: float) -> None:
        """Set the sampling parameters this model actually accepts."""
        if self.is_reasoning_first:
            if self.effort:
                request_kwargs["reasoning_effort"] = self.effort
        else:
            request_kwargs["temperature"] = temperature

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

        request_kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": openai_messages,
            "max_completion_tokens": max_tokens,
        }
        self._apply_sampling_params(request_kwargs, temperature)

        response = await self.client.chat.completions.create(**request_kwargs)

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
        system_prompt: SystemPrompt,
        messages: list[dict],
        tools: list[dict],
        max_tokens: int,
        temperature: float,
        tool_choice: str | None = None,
    ) -> ChatResponse:
        # (static, dynamic) prompts are joined static-first: OpenAI's automatic
        # prompt caching keys on a stable request prefix, so the per-turn date
        # block must come last.
        openai_messages = [{"role": "system", "content": join_system_prompt(system_prompt)}]
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

        request_kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": openai_messages,
            "tools": openai_tools,
            "max_completion_tokens": max_tokens,
        }
        self._apply_sampling_params(request_kwargs, temperature)
        if tool_choice is not None:
            request_kwargs["tool_choice"] = tool_choice

        response = await self.client.chat.completions.create(**request_kwargs)

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
