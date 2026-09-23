"""AI service for LLM-powered features (OpenAI /v1/responses backend).

Same tool-use interface as OpenAIService, against the Responses API instead of
Chat Completions. This is the only way to combine reasoning with function
tools: on /v1/chat/completions OpenAI deliberately rejects that combination for
the gpt-5.6+ family, and GPT-6 drops function calling there entirely.

Requests are stateless (``store=False``): we never let OpenAI retain the
conversation, and we replay the reasoning items ourselves inside the turn.
Patient conversations are medical data, so this is a deliberate choice, not a
default we inherited.
"""

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

# Output items that must be replayed on the next call within a turn. Reasoning
# items are the reason this service exists: without them the model re-derives
# its plan after every tool result, which costs tokens and degrades tool choice.
# They are encrypted blobs — we forward them, we never read them.
REPLAYABLE_ITEM_TYPES = ("reasoning", "function_call", "message")


class OpenAIResponsesService(BaseAIService):
    """LLM interactions via the OpenAI Responses API, with reasoning enabled."""

    def __init__(
        self,
        timeout: int = 60,
        max_retries: int = 2,
        model: str | None = None,
        reasoning_effort: str | None = None,
    ):
        # Reasoning turns are slower than a plain completion, so the default
        # timeout is higher than the Chat Completions service's 30s.
        self.client = AsyncOpenAI(
            api_key=settings.open_ai_key,
            timeout=timeout,
        )
        self.max_retries = max_retries
        self.model = model or settings.open_ai_model
        self.effort = (
            reasoning_effort
            if reasoning_effort is not None
            else settings.open_ai_reasoning_effort
        )

    # ------------------------------------------------------------------
    # Request building
    # ------------------------------------------------------------------

    def _base_kwargs(self, system_prompt: SystemPrompt, max_tokens: int) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "model": self.model,
            # (static, dynamic) joined static-first: prompt caching keys on a
            # stable prefix, so the per-turn date block must come last.
            "instructions": join_system_prompt(system_prompt),
            "max_output_tokens": max_tokens,
            "store": False,
        }
        if self.effort:
            kwargs["reasoning"] = {"effort": self.effort}
        return kwargs

    @staticmethod
    def _dump(item: Any) -> dict:
        """Convert an SDK output item back into a plain input item."""
        if isinstance(item, dict):
            return item
        return item.model_dump(exclude_none=True)

    # ------------------------------------------------------------------
    # Response parsing
    # ------------------------------------------------------------------

    def _parse(self, response: Any) -> ChatResponse:
        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []
        replay: list[dict] = []

        for item in response.output:
            item_type = getattr(item, "type", None)

            if item_type in REPLAYABLE_ITEM_TYPES:
                replay.append(self._dump(item))

            if item_type == "function_call":
                tool_calls.append(ToolCall(
                    id=item.call_id,
                    name=item.name,
                    arguments=json.loads(item.arguments) if item.arguments else {},
                ))
            elif item_type == "message":
                for block in item.content or []:
                    if getattr(block, "type", None) == "output_text":
                        text_parts.append(block.text)

        usage = response.usage
        reasoning_tokens = 0
        if usage and getattr(usage, "output_tokens_details", None):
            reasoning_tokens = usage.output_tokens_details.reasoning_tokens or 0

        logger.info(
            "llm_chat_with_tools_success",
            tokens_input=usage.input_tokens if usage else 0,
            tokens_output=usage.output_tokens if usage else 0,
            tokens_reasoning=reasoning_tokens,
            status=response.status,
            tool_calls=len(tool_calls),
        )

        # A truncated response silently loses the reply (and, mid-loop, the tool
        # call that was about to be made), so it must be visible in the logs.
        if response.status == "incomplete":
            reason = getattr(response.incomplete_details, "reason", None)
            logger.warning(
                "llm_response_incomplete",
                reason=reason,
                max_output_tokens=response.max_output_tokens,
                effort=self.effort,
            )

        return ChatResponse(
            text="".join(text_parts) or None,
            tool_calls=tool_calls,
            stop_reason=response.status or "completed",
            raw_message=replay,
        )

    # ------------------------------------------------------------------
    # BaseAIService interface
    # ------------------------------------------------------------------

    async def _raw_chat(
        self,
        system_prompt: str,
        messages: list[dict],
        max_tokens: int,
        temperature: float,
    ) -> str:
        kwargs = self._base_kwargs(system_prompt, max_tokens)
        kwargs["input"] = messages

        logger.debug(
            "llm_chat_request",
            model=self.model,
            messages_count=len(messages),
            max_tokens=max_tokens,
        )

        response = await self.client.responses.create(**kwargs)
        return response.output_text or ""

    async def _raw_chat_with_tools(
        self,
        system_prompt: SystemPrompt,
        messages: list[dict],
        tools: list[dict],
        max_tokens: int,
        temperature: float,
        tool_choice: str | None = None,
    ) -> ChatResponse:
        # Responses tools are "internally tagged": name/description/parameters
        # sit at the top level, not nested under a "function" key.
        responses_tools = [
            {
                "type": "function",
                "name": tool["name"],
                "description": tool.get("description", ""),
                "parameters": tool.get("input_schema", {}),
            }
            for tool in tools
        ]

        kwargs = self._base_kwargs(system_prompt, max_tokens)
        kwargs["input"] = messages
        kwargs["tools"] = responses_tools
        if tool_choice is not None:
            kwargs["tool_choice"] = tool_choice

        logger.debug(
            "llm_chat_with_tools_request",
            model=self.model,
            messages_count=len(messages),
            tools_count=len(tools),
            max_tokens=max_tokens,
            effort=self.effort,
        )

        response = await self.client.responses.create(**kwargs)
        return self._parse(response)

    def build_tool_result_messages(
        self,
        assistant_message: Any,
        tool_results: list[dict],
    ) -> list[dict]:
        """
        Build Responses-format input items for tool results.

        `assistant_message` is the list of replayable output items (reasoning +
        function calls), which must be fed back verbatim before their outputs —
        dropping the reasoning items is what makes a reasoning model forget its
        own plan between tool calls.
        """
        result_messages: list[dict] = list(assistant_message or [])
        for result in tool_results:
            content = result["result"]
            if not isinstance(content, str):
                content = json.dumps(content, ensure_ascii=False)
            result_messages.append({
                "type": "function_call_output",
                "call_id": result["tool_call_id"],
                "output": content,
            })
        return result_messages
