"""Shared machinery for the patient and doctor tool-use conversation managers.

Both managers do the same dance: extract the incoming WhatsApp message
(transcribing voice notes), run the LLM tool-use loop on a working copy of
the history, and persist only plain text turns. The subclasses own their
prompts, tools, session storage and side effects.
"""

from __future__ import annotations

import json
import time
from typing import Any, Optional

from app.core.ai_selection import current_selection
from app.core.exceptions import ConversationError
from app.modules.ai import get_ai_service
from app.modules.ai.base_service import join_system_prompt
from app.modules.ai.transcription import transcribe_whatsapp_audio
from app.core.exceptions import AIServiceError
from app.modules.conversation.grounding import (
    CORRECTION_PREFIX,
    Evidence,
    correction_message,
    tool_result_texts,
    validate_reply,
)
from app.modules.conversation.tracing import TurnTrace
from app.utils.dates import now_mx
from app.utils.logger import get_logger

logger = get_logger(__name__)

# Must fit batch instructions (e.g. the doctor rescheduling several
# appointments in one message: lookup + N reschedules + N draft notices).
MAX_TOOL_ITERATIONS = 10

# Budget for the corrective pass after a reply failed validation: enough to
# re-query availability or execute the action it had only claimed.
CORRECTION_TOOL_ITERATIONS = 4


def _succeeded(result) -> bool:
    """Whether a tool result reports a completed action (or a non-empty read)."""
    if not isinstance(result, dict) or "error" in result or "existing_appointment" in result:
        return False
    if "appointments" in result and not result["appointments"]:
        return False
    return True


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

    # Sent instead of a reply that, even after a corrective pass, still claims
    # an action no tool performed. Subclasses word it for their audience.
    UNGROUNDED_FALLBACK = (
        "Disculpa, tuve un problema y no se realizó ningún cambio. "
        "¿Me lo repites, por favor?"
    )

    def new_trace(self, office, channel: str, **fields) -> TurnTrace:
        """A TurnTrace pre-filled with the model this turn will use."""
        selection = current_selection()
        return TurnTrace(
            office_id=office.id,
            channel=channel,
            provider=selection.provider,
            model=getattr(self.ai_service, "model", None) or selection.model,
            reasoning_effort=getattr(self.ai_service, "effort", None) or None,
            **fields,
        )

    async def run_tool_loop(
        self,
        system_prompt,
        working_messages: list[dict],
        tools: list[dict],
        execute,
        ctx,
        log_prefix: str,
        mutating_tools: frozenset[str] = frozenset(),
        tool_claims: Optional[dict[str, frozenset[str]]] = None,
        parallel_tool_calls: Optional[bool] = None,
        trace: Optional[TurnTrace] = None,
    ) -> str:
        """Run the tool-use loop on `working_messages` until the LLM answers.

        `working_messages` is a per-turn scratch list — it accumulates the
        provider-specific tool chain and is discarded by the caller after the
        turn.

        Three guarantees are enforced here, once, for both flows:

        1. A mutating tool called twice with identical arguments in the same turn
           runs once; the second call gets the first one's result. The model is
           free to emit parallel tool calls, and a repeated write is never what
           it means: booking the same slot twice had the second call collide
           with the first ("ya tienes una cita ese día") and the model relayed
           that as the truth about the patient's agenda.
        2. Every executed write is recorded in `ctx.state.recent_actions` with a
           code-written summary and the claims it backs (`tool_claims`), so the
           next turns know what really happened — not what the model said.
        3. The final reply is checked against the evidence (grounding.py). A
           reply that claims an unexecuted action, quotes a time no tool gave,
           or pairs a date with the wrong weekday gets ONE corrective pass. If
           the claim problem survives it, a safe fallback is sent instead;
           residual time/date findings are sent but recorded in the trace.
        """
        tool_claims = tool_claims or {}
        state = getattr(ctx, "state", None)
        write_results: dict[str, dict] = {}
        turn_results: list[dict] = []

        text = await self._loop_until_text(
            system_prompt, working_messages, tools, execute, ctx, log_prefix,
            mutating_tools, tool_claims, parallel_tool_calls, trace,
            write_results, turn_results, state, MAX_TOOL_ITERATIONS,
        )

        for attempt in (1, 2):
            violations = validate_reply(
                text,
                self._evidence(
                    system_prompt, working_messages, turn_results, state, tool_claims
                ),
            )
            if not violations:
                return text
            if trace is not None:
                trace.add_violations(violations, attempt)
            logger.warning(
                f"{log_prefix}_reply_not_grounded",
                attempt=attempt,
                violations=[v.kind for v in violations],
            )
            if attempt == 2:
                break
            first_text = text
            working_messages.append({"role": "assistant", "content": text})
            working_messages.append(
                {"role": "user", "content": correction_message(violations)}
            )
            try:
                text = await self._loop_until_text(
                    system_prompt, working_messages, tools, execute, ctx, log_prefix,
                    mutating_tools, tool_claims, parallel_tool_calls, trace,
                    write_results, turn_results, state, CORRECTION_TOOL_ITERATIONS,
                )
            except AIServiceError as e:
                # The model went away mid-correction. Don't turn the whole turn
                # into "problema técnico" and hide what was already done: keep
                # the first reply unless its problem was a false claim.
                logger.error(f"{log_prefix}_correction_failed", error=str(e))
                text = first_text
                break

        if any(v.kind == "claimed_action" for v in violations):
            if trace is not None:
                trace.outcome = "fallback"
            return self._fallback_reply(turn_results, mutating_tools)
        return text

    def _fallback_reply(self, turn_results, mutating_tools) -> str:
        """The reply sent when a false claim survived the corrective pass.

        If a write DID succeed this turn, say exactly that, from the summaries
        the code wrote — "no se realizó ningún cambio" over a real booking sends
        the patient off to book again.
        """
        done = [
            result["summary"]
            for name, result in turn_results
            if name in mutating_tools
            and _succeeded(result)
            and isinstance(result.get("summary"), str)
        ]
        if not done:
            return self.UNGROUNDED_FALLBACK
        return "Listo. " + ". ".join(s.rstrip(".") for s in done) + "."

    @staticmethod
    def _evidence(
        system_prompt, working_messages, turn_results, state, tool_claims
    ) -> Evidence:
        """What the reply may draw facts from: tools, state, prompt, user words."""
        texts = [join_system_prompt(system_prompt)]
        texts += [
            m["content"] for m in working_messages
            if m.get("role") == "user"
            and isinstance(m.get("content"), str)
            and not m["content"].startswith(CORRECTION_PREFIX)
        ]
        texts += tool_result_texts(r for _, r in turn_results)
        claims = set(state.successful_claims()) if state is not None else set()
        # This turn's successful calls — including reads: a lookup that found the
        # appointment backs "tu cita quedó agendada" as much as the booking did.
        for name, result in turn_results:
            if _succeeded(result):
                claims |= tool_claims.get(name, frozenset())
        return Evidence.build(today=now_mx().date(), claims=claims, texts=texts)

    async def _loop_until_text(
        self,
        system_prompt,
        working_messages: list[dict],
        tools: list[dict],
        execute,
        ctx,
        log_prefix: str,
        mutating_tools: frozenset[str],
        tool_claims: dict[str, frozenset[str]],
        parallel_tool_calls: Optional[bool],
        trace: Optional[TurnTrace],
        write_results: dict[str, dict],
        turn_results: list[dict],
        state,
        max_iterations: int,
    ) -> str:
        """Call the model, run its tool calls, repeat until it answers in text.

        If the iteration budget runs out, one final call with tool_choice="none"
        lets the model compose a reply from what it already gathered instead of
        returning a canned apology.
        """
        for iteration in range(max_iterations):
            response = await self.ai_service.chat_with_tools(
                system_prompt=system_prompt,
                messages=working_messages,
                tools=tools,
                parallel_tool_calls=parallel_tool_calls,
            )
            if trace is not None:
                trace.add_llm_call(response)

            if not response.tool_calls:
                return response.text or ""

            logger.info(
                f"{log_prefix}_tool_calls",
                iteration=iteration + 1,
                tools=[tc.name for tc in response.tool_calls],
            )

            tool_results = []
            for tc in response.tool_calls:
                memo_key = None
                if tc.name in mutating_tools:
                    # The pending draft is part of what a write acts on: a
                    # no-argument confirm after a NEW draft is a different call.
                    draft = getattr(state, "draft", None) if state is not None else None
                    memo_key = (
                        f"{tc.name}:{json.dumps(tc.arguments, sort_keys=True, default=str)}"
                        f":{draft.created_at if draft else ''}"
                    )

                started = time.monotonic()
                duplicate = memo_key is not None and memo_key in write_results
                if duplicate:
                    logger.info(
                        f"{log_prefix}_duplicate_write_suppressed",
                        tool=tc.name,
                    )
                    result = write_results[memo_key]
                else:
                    result = await execute(tc.name, tc.arguments, ctx)
                    if memo_key is not None:
                        # Only a success is replayed; a failed write may be
                        # legitimately retried in the same turn.
                        if _succeeded(result):
                            write_results[memo_key] = result
                        if state is not None:
                            self._record_action(state, tc.name, result, tool_claims)

                turn_results.append((tc.name, result))
                if trace is not None:
                    trace.add_tool_call(
                        tc.name,
                        tc.arguments,
                        result,
                        int((time.monotonic() - started) * 1000),
                        duplicate,
                    )
                tool_results.append({
                    "tool_call_id": tc.id,
                    "result": result,
                })

            result_messages = self.ai_service.build_tool_result_messages(
                response.raw_message, tool_results
            )
            working_messages.extend(result_messages)

        # Budget exhausted — close the turn with the information gathered so far.
        logger.warning(f"{log_prefix}_tool_loop_max_iterations", max=max_iterations)
        try:
            response = await self.ai_service.chat_with_tools(
                system_prompt=system_prompt,
                messages=working_messages,
                tools=tools,
                tool_choice="none",
            )
            if trace is not None:
                trace.add_llm_call(response)
            if response.text and response.text.strip():
                return response.text
        except Exception as e:
            logger.error(f"{log_prefix}_final_reply_failed", error=str(e))
        return "Disculpa, tuve un problema procesando tu solicitud. ¿Podrías intentarlo de nuevo?"

    @staticmethod
    def _record_action(state, tool_name: str, result, tool_claims) -> None:
        """Record an executed write in the conversation's working memory."""
        ok = _succeeded(result)
        summary = None
        if isinstance(result, dict):
            for key in ("summary", "message", "error"):
                value = result.get(key)
                if isinstance(value, str) and value.strip():
                    summary = value.strip()
                    break
        state.record_action(
            tool=tool_name,
            ok=ok,
            summary=f"{tool_name}: {summary}" if summary else tool_name,
            claims=sorted(tool_claims.get(tool_name, ())) if ok else [],
            at=now_mx(),
        )
