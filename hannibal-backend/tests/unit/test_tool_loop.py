"""The shared tool loop: dedupe, action ledger, grounding correction, fallback.

Runs against a scripted fake model — no network, no database.
"""

from app.core.exceptions import AIServiceError
from app.modules.ai.base_service import ChatResponse, ToolCall
from app.modules.conversation.base_manager import BaseToolConversationManager
from app.modules.conversation.state import ConversationState
from app.modules.conversation.tracing import TurnTrace


class FakeAI:
    """Returns scripted responses in order and records every call."""

    model = "fake-model"
    effort = None

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    async def chat_with_tools(self, **kwargs):
        self.calls.append(kwargs)
        step = self.responses.pop(0)
        if isinstance(step, Exception):
            raise step
        return step

    def build_tool_result_messages(self, raw, tool_results):
        return [{"role": "tool", "content": str(r["result"])} for r in tool_results]


class Manager(BaseToolConversationManager):
    def _non_text_placeholder(self, msg_type, caption):
        return ""


class Ctx:
    def __init__(self):
        self.state = ConversationState()


def text(t):
    return ChatResponse(text=t)


def calls(*pairs):
    return ChatResponse(
        text=None,
        tool_calls=[ToolCall(id=f"c{i}", name=n, arguments=a) for i, (n, a) in enumerate(pairs)],
    )


async def run(responses, execute, claims=None, mutating=frozenset({"write"})):
    ai = FakeAI(responses)
    mgr = Manager(meta_client=None, ai_service=ai)
    ctx = Ctx()
    trace = TurnTrace(office_id=None, channel="patient")
    reply = await mgr.run_tool_loop(
        ("static", "dynamic"),
        [{"role": "user", "content": "hola"}],
        tools=[],
        execute=execute,
        ctx=ctx,
        log_prefix="test",
        mutating_tools=mutating,
        tool_claims=claims or {"write": frozenset({"book"})},
        trace=trace,
    )
    return reply, ai, ctx, trace


async def test_identical_parallel_writes_run_once():
    executed = []

    async def execute(name, args, ctx):
        executed.append(name)
        return {"success": True, "summary": "Cita agendada"}

    reply, _, ctx, trace = await run(
        [calls(("write", {"x": 1}), ("write", {"x": 1})), text("Listo.")], execute
    )
    assert executed == ["write"]
    assert [t["duplicate"] for t in trace.tool_calls] == [False, True]
    assert len(ctx.state.recent_actions) == 1


async def test_successful_write_is_recorded_with_its_claims():
    async def execute(name, args, ctx):
        return {"success": True, "summary": "Cita agendada: jueves"}

    reply, _, ctx, _ = await run(
        [calls(("write", {})), text("Tu cita quedó agendada.")], execute
    )
    assert reply == "Tu cita quedó agendada."
    action = ctx.state.recent_actions[0]
    assert action.ok and action.claims == ["book"] and "jueves" in action.summary


async def test_failed_write_backs_no_claim():
    async def execute(name, args, ctx):
        return {"error": "ocupado"}

    _, _, ctx, _ = await run([calls(("write", {})), text("No se pudo.")], execute)
    assert ctx.state.recent_actions[0].ok is False
    assert ctx.state.successful_claims() == set()


async def test_ungrounded_claim_gets_one_correction():
    async def execute(name, args, ctx):
        return {"success": True}

    reply, ai, _, trace = await run(
        [text("Listo, tu cita quedó agendada."), text("¿Te confirmo el jueves?")], execute
    )
    assert reply == "¿Te confirmo el jueves?"
    # The correction pass saw the rejected reply and the internal note.
    last_messages = ai.calls[1]["messages"]
    assert last_messages[-2] == {"role": "assistant", "content": "Listo, tu cita quedó agendada."}
    assert "Nota interna" in last_messages[-1]["content"]
    assert [v["kind"] for v in trace.violations] == ["claimed_action"]


async def test_persistent_false_claim_falls_back():
    async def execute(name, args, ctx):
        return {"success": True}

    reply, _, _, trace = await run(
        [text("Ya te agendé."), text("Ya quedó agendada, no te preocupes.")], execute
    )
    assert reply == Manager.UNGROUNDED_FALLBACK
    assert trace.outcome == "fallback"


async def test_correction_pass_may_execute_the_claimed_action():
    async def execute(name, args, ctx):
        return {"success": True, "summary": "Cita agendada"}

    reply, _, ctx, _ = await run(
        [text("Tu cita quedó agendada."), calls(("write", {})), text("Tu cita quedó agendada.")],
        execute,
    )
    assert reply == "Tu cita quedó agendada."
    assert ctx.state.successful_claims() == {"book"}


async def test_invented_time_is_corrected():
    async def execute(name, args, ctx):
        return {"days": [{"slots": [{"slot_id": "2026-09-24T16:00", "label": "4:00 PM"}]}]}

    reply, _, _, trace = await run(
        [
            calls(("read", {})),
            text("Tengo 4:00 PM y 6:00 PM."),
            text("Tengo 4:00 PM."),
        ],
        execute,
    )
    assert reply == "Tengo 4:00 PM."
    assert trace.violations[0]["kind"] == "unsupported_time"


async def test_read_that_finds_appointments_backs_existence_claim():
    async def execute(name, args, ctx):
        return {"appointments": [{"id": "1", "label": "jueves 24 de septiembre a las 4:00 PM"}]}

    reply, _, _, trace = await run(
        [calls(("lookup", {})), text("Sí, tu cita quedó agendada para el jueves 24 de septiembre a las 4:00 PM.")],
        execute,
        claims={"lookup": frozenset({"book"})},
    )
    assert trace.violations == []


async def test_budget_exhaustion_closes_with_text():
    async def execute(name, args, ctx):
        return {"ok": True}

    responses = [calls(("read", {"i": i})) for i in range(10)] + [text("Resumen.")]
    reply, ai, _, _ = await run(responses, execute)
    assert reply == "Resumen."
    assert ai.calls[-1].get("tool_choice") == "none"


async def test_invented_time_that_survives_is_recorded_twice():
    # The correction note quotes the bad time; it must not count as evidence.
    async def execute(name, args, ctx):
        return {"days": [{"slots": [{"slot_id": "2026-09-24T16:00", "label": "4:00 PM"}]}]}

    reply, _, _, trace = await run(
        [calls(("read", {})), text("Tengo 6:00 PM."), text("Sí, tengo 6:00 PM.")], execute
    )
    assert [v["attempt"] for v in trace.violations] == [1, 2]
    assert reply == "Sí, tengo 6:00 PM."  # time findings are sent, but recorded


async def test_fallback_reports_writes_that_did_happen():
    async def execute(name, args, ctx):
        return {"success": True, "summary": "Cita agendada: Juan, jueves 24 de septiembre a las 4:00 PM"}

    reply, _, _, trace = await run(
        [
            calls(("write", {})),
            text("Listo, agendada. Ya le avisé al doctor."),
            text("Agendada y ya le avisé al doctor."),
        ],
        execute,
    )
    assert trace.outcome == "fallback"
    assert reply.startswith("Listo. Cita agendada: Juan")
    assert "no se realizó" not in reply


async def test_failed_write_is_not_replayed_to_a_retry():
    results = iter([{"error": "ocupado"}, {"success": True, "summary": "ok"}])

    async def execute(name, args, ctx):
        return next(results)

    _, _, ctx, trace = await run(
        [calls(("write", {"x": 1})), calls(("write", {"x": 1})), text("Listo, quedó agendada.")],
        execute,
    )
    assert [t["duplicate"] for t in trace.tool_calls] == [False, False]
    assert ctx.state.successful_claims() == {"book"}


async def test_model_failure_during_correction_keeps_first_reply():
    async def execute(name, args, ctx):
        return {"days": [{"slots": [{"slot_id": "2026-09-24T16:00", "label": "4:00 PM"}]}]}

    reply, _, _, _ = await run(
        [calls(("read", {})), text("Tengo 4:00 PM y 6:00 PM."), AIServiceError("down")],
        execute,
    )
    assert reply == "Tengo 4:00 PM y 6:00 PM."
