"""Per-turn trace of what the assistant did (ai_turn_traces).

The tool loop fills a TurnTrace as it runs; the manager persists it when the
turn ends — including a turn that raised, which is exactly the one worth
reading. Persisting uses its own session so the trace survives the turn's
rollback and a trace failure can never fail the turn.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any, Optional

from sqlalchemy import delete

from app.db.models import AiTurnTrace
from app.utils.dates import now_mx
from app.utils.logger import get_logger

logger = get_logger(__name__)

# Tool results can be large (a week of slots); the trace keeps enough to
# diagnose without storing every payload whole.
MAX_RESULT_CHARS = 4000
TRACE_RETENTION_DAYS = 30


def _truncate(value: Any) -> Any:
    text = json.dumps(value, ensure_ascii=False, default=str)
    if len(text) <= MAX_RESULT_CHARS:
        return value
    return {"truncated": text[:MAX_RESULT_CHARS]}


@dataclass
class TurnTrace:
    office_id: uuid.UUID
    channel: str  # "patient" | "doctor"
    whatsapp_id: Optional[str] = None
    conversation_id: Optional[uuid.UUID] = None
    user_text: Optional[str] = None
    provider: Optional[str] = None
    model: Optional[str] = None
    reasoning_effort: Optional[str] = None
    tool_calls: list[dict] = field(default_factory=list)
    violations: list[dict] = field(default_factory=list)
    reply: Optional[str] = None
    outcome: str = "ok"
    error: Optional[str] = None
    llm_calls: int = 0
    tokens_input: int = 0
    tokens_output: int = 0
    started: float = field(default_factory=time.monotonic)

    def add_llm_call(self, response) -> None:
        self.llm_calls += 1
        self.tokens_input += getattr(response, "tokens_input", 0) or 0
        self.tokens_output += getattr(response, "tokens_output", 0) or 0

    def add_tool_call(
        self, name: str, arguments: dict, result: Any, duration_ms: int, duplicate: bool
    ) -> None:
        self.tool_calls.append({
            "name": name,
            "arguments": arguments,
            "result": _truncate(result),
            "duration_ms": duration_ms,
            "duplicate": duplicate,
        })

    def add_violations(self, violations, attempt: int) -> None:
        for v in violations:
            self.violations.append({**v.as_dict(), "attempt": attempt})

    @property
    def latency_ms(self) -> int:
        return int((time.monotonic() - self.started) * 1000)


async def persist_trace(trace: TurnTrace) -> None:
    """Write the trace in its own session. Best-effort: never raises."""
    from app.db.base import get_async_session_maker

    try:
        async with get_async_session_maker()() as session:
            session.add(AiTurnTrace(
                id=uuid.uuid4(),
                office_id=trace.office_id,
                conversation_id=trace.conversation_id,
                channel=trace.channel,
                whatsapp_id=trace.whatsapp_id,
                provider=trace.provider,
                model=trace.model,
                reasoning_effort=trace.reasoning_effort,
                user_text=trace.user_text,
                tool_calls=trace.tool_calls or None,
                grounding_violations=trace.violations or None,
                reply=trace.reply,
                outcome=trace.outcome,
                error=trace.error,
                llm_calls=trace.llm_calls,
                tokens_input=trace.tokens_input,
                tokens_output=trace.tokens_output,
                latency_ms=trace.latency_ms,
            ))
            await session.commit()
    except Exception as e:
        logger.warning("turn_trace_persist_failed", error=str(e))

    logger.info(
        "turn_trace",
        office_id=str(trace.office_id),
        channel=trace.channel,
        model=trace.model,
        outcome=trace.outcome,
        tools=[t["name"] for t in trace.tool_calls],
        violations=[v["kind"] for v in trace.violations],
        llm_calls=trace.llm_calls,
        tokens_input=trace.tokens_input,
        tokens_output=trace.tokens_output,
        latency_ms=trace.latency_ms,
    )


async def prune_old_traces(db) -> int:
    """Delete traces older than TRACE_RETENTION_DAYS. Returns rows deleted."""
    cutoff = now_mx() - timedelta(days=TRACE_RETENTION_DAYS)
    result = await db.execute(delete(AiTurnTrace).where(AiTurnTrace.created_at < cutoff))
    await db.commit()
    return result.rowcount or 0
