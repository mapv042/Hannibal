"""Shared machinery for the patient and doctor tool-use conversation managers.

Both managers do the same dance: extract the incoming WhatsApp message
(transcribing voice notes), run the LLM tool-use loop on a working copy of
the history, and persist only plain text turns. The subclasses own their
prompts, tools, session storage and side effects.
"""

from __future__ import annotations

from typing import Any, Optional

from app.core.exceptions import ConversationError
from app.modules.ai import get_ai_service
from app.modules.ai.transcription import transcribe_whatsapp_audio
from app.utils.logger import get_logger

logger = get_logger(__name__)

MAX_TOOL_ITERATIONS = 5


class BaseToolConversationManager:
    """Base class: message extraction + tool-use loop + text-only history."""

    # Subclasses override to word non-text placeholders for their audience.
    def _non_text_placeholder(self, msg_type: str, caption: str) -> str:
        raise NotImplementedError

    def _voice_transcript_text(self, transcript: str) -> str:
        return f"[Mensaje de voz transcrito]: {transcript}"

    def __init__(self, meta_client, ai_service=None):
        self.meta_client = meta_client
        self.ai_service = ai_service or get_ai_service()

    # ------------------------------------------------------------------
    # Incoming message extraction
    # ------------------------------------------------------------------

    async def extract_message(self, message: dict[str, Any], office) -> dict[str, Any]:
        """Turn a raw webhook message dict into {from, text, id}.

        Handles text, interactive replies (button/list — the chosen title
        becomes the text), voice notes (transcribed via Whisper when
        available) and captioned media. Anything else becomes a placeholder
        the LLM knows how to answer.
        """
        try:
            msg_type = message.get("type", "text")

            if msg_type == "text":
                text = message["text"]["body"]
            elif msg_type == "interactive":
                interactive = message.get("interactive") or {}
                reply = (
                    interactive.get("button_reply")
                    or interactive.get("list_reply")
                    or {}
                )
                text = reply.get("title") or reply.get("id") or "[Respuesta interactiva]"
            elif msg_type == "audio":
                media_id = (message.get("audio") or {}).get("id", "")
                transcript = None
                if media_id:
                    transcript = await transcribe_whatsapp_audio(
                        self.meta_client, office, media_id
                    )
                if transcript:
                    text = self._voice_transcript_text(transcript)
                else:
                    text = self._non_text_placeholder("audio", "")
            else:
                caption = ""
                if msg_type in ("image", "video", "document"):
                    caption = (message.get(msg_type) or {}).get("caption", "")
                text = self._non_text_placeholder(msg_type, caption)

            return {
                "from": message["from"],
                "text": text,
                "id": message.get("id", ""),
            }
        except KeyError as e:
            raise ConversationError(f"Invalid message payload: {str(e)}") from e

    # ------------------------------------------------------------------
    # History handling — persisted history is plain text turns only
    # ------------------------------------------------------------------

    @staticmethod
    def sanitize_history(history: list[dict]) -> list[dict]:
        """Keep only plain user/assistant text turns.

        Persisted history is provider-agnostic: tool-call chains live only in
        the per-turn working copy. This also cleans sessions written before
        this convention (which stored provider-specific tool messages).
        """
        return [
            m for m in history
            if m.get("role") in ("user", "assistant")
            and isinstance(m.get("content"), str)
            and not m.get("tool_calls")
        ]

    # ------------------------------------------------------------------
    # Tool-use loop
    # ------------------------------------------------------------------

    async def run_tool_loop(
        self,
        system_prompt,
        working_messages: list[dict],
        tools: list[dict],
        execute,
        ctx,
        log_prefix: str,
    ) -> str:
        """Run the tool-use loop on `working_messages` until the LLM answers.

        `working_messages` is a per-turn scratch list — it accumulates the
        provider-specific tool chain and is discarded by the caller after the
        turn. If the iteration budget runs out, one final call with
        tool_choice="none" lets the model compose a reply from what it
        already gathered instead of returning a canned apology.
        """
        for iteration in range(MAX_TOOL_ITERATIONS):
            response = await self.ai_service.chat_with_tools(
                system_prompt=system_prompt,
                messages=working_messages,
                tools=tools,
            )

            if not response.tool_calls:
                return response.text or ""

            logger.info(
                f"{log_prefix}_tool_calls",
                iteration=iteration + 1,
                tools=[tc.name for tc in response.tool_calls],
            )

            tool_results = []
            for tc in response.tool_calls:
                result = await execute(tc.name, tc.arguments, ctx)
                tool_results.append({
                    "tool_call_id": tc.id,
                    "result": result,
                })

            result_messages = self.ai_service.build_tool_result_messages(
                response.raw_message, tool_results
            )
            working_messages.extend(result_messages)

        # Budget exhausted — close the turn with the information gathered so far.
        logger.warning(f"{log_prefix}_tool_loop_max_iterations", max=MAX_TOOL_ITERATIONS)
        try:
            response = await self.ai_service.chat_with_tools(
                system_prompt=system_prompt,
                messages=working_messages,
                tools=tools,
                tool_choice="none",
            )
            if response.text and response.text.strip():
                return response.text
        except Exception as e:
            logger.error(f"{log_prefix}_final_reply_failed", error=str(e))
        return "Disculpa, tuve un problema procesando tu solicitud. ¿Podrías intentarlo de nuevo?"
