"""End-to-end patient flow against a real database and Redis, with a scripted model.

Everything but the LLM is real: ConversationManager.process, the tool handlers,
book_appointment, the availability engine, the Redis session (with its
ConversationState), the reply validator and the ai_turn_traces rows. The model
is replaced by a script, so what's under test is the machinery — the part that
must hold no matter which model answers.

DESTRUCTIVE: it wipes and reseeds the database (the simulator's seed). It only
runs when RUN_INTEGRATION=1 and DATABASE_URL points at localhost:

    docker run -d --name hannibal-eval-pg -e POSTGRES_PASSWORD=eval \\
        -e POSTGRES_DB=hannibal_sim -p 55432:5432 postgres:16-alpine
    export DATABASE_URL=postgresql://postgres:eval@localhost:55432/hannibal_sim
    export REDIS_URL=redis://localhost:6379/7 WHATSAPP_TRANSPORT=fake
    alembic upgrade head
    RUN_INTEGRATION=1 pytest tests/integration -v
"""

from __future__ import annotations

import os
import uuid
from datetime import timedelta

import pytest
import redis.asyncio as aioredis
from sqlalchemy import select

from app.config import settings

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_INTEGRATION") != "1"
    or not any(h in settings.database_url for h in ("localhost", "127.0.0.1")),
    reason="destructive: needs RUN_INTEGRATION=1 and a local DATABASE_URL",
)

from app.db.base import dispose_engine, get_async_session_maker  # noqa: E402
from app.db.models import AiTurnTrace, Appointment  # noqa: E402
from app.modules.ai.base_service import ChatResponse, ToolCall  # noqa: E402
from app.modules.conversation.manager import ConversationManager  # noqa: E402
from app.modules.conversation.session_store import SessionStore  # noqa: E402
from app.modules.sim import seed as sim_seed  # noqa: E402
from app.utils.dates import now_mx  # noqa: E402

PATIENT = sim_seed.DEFAULT_PATIENT_PHONE


class Recorder:
    """WhatsApp client stand-in: keeps what would have been sent."""

    def __init__(self):
        self.sent: list[str] = []

    async def send_text_message(self, phone_number_id, token, to, text):
        self.sent.append(text)
        return f"wamid.test.{uuid.uuid4().hex}"


class ScriptedAI:
    """Plays back responses; a callable step sees the last tool results."""

    model = "scripted"
    effort = None

    def __init__(self):
        self.steps: list = []
        self.last_results: list = []

    def then(self, *steps):
        self.steps.extend(steps)

    async def chat_with_tools(self, **kwargs):
        step = self.steps.pop(0)
        return step(self.last_results) if callable(step) else step

    def build_tool_result_messages(self, raw, tool_results):
        self.last_results = [r["result"] for r in tool_results]
        return [{"role": "user", "content": f"[tool] {r['result']}"} for r in tool_results]


def call(name, **args):
    return ChatResponse(text=None, tool_calls=[ToolCall(id=uuid.uuid4().hex, name=name, arguments=args)])


def say(text):
    return ChatResponse(text=text)


@pytest.fixture
async def env():
    redis_client = aioredis.from_url(settings.redis_url, decode_responses=True)
    async with get_async_session_maker()() as db:
        office = await sim_seed.reset(db)
    await redis_client.delete(f"session:{PATIENT}:{office.id}")
    ai, wa = ScriptedAI(), Recorder()
    manager = ConversationManager(SessionStore(redis_client), wa, ai_service=ai)

    async def turn(text):
        async with get_async_session_maker()() as db:
            fresh_office = await db.get(type(office), office.id)
            msg = {"from": PATIENT, "id": f"wamid.in.{uuid.uuid4().hex}", "type": "text",
                   "text": {"body": text}}
            await manager.process(fresh_office, msg, db)
        return wa.sent[-1]

    async def appointments():
        async with get_async_session_maker()() as db:
            return list((await db.execute(
                select(Appointment).where(Appointment.office_id == office.id)
                .order_by(Appointment.created_at)
            )).scalars().all())

    async def session():
        return await SessionStore(redis_client).get_session(PATIENT, str(office.id))

    yield {"office": office, "ai": ai, "turn": turn, "appointments": appointments,
           "session": session, "redis": redis_client}
    await redis_client.aclose()
    await dispose_engine()


def next_weekday(weekday: int):
    today = now_mx().date()
    days = (weekday - today.weekday()) % 7 or 7
    return today + timedelta(days=days)


async def test_book_is_two_steps_and_state_carries_the_slot(env):
    ai, turn = env["ai"], env["turn"]
    tue = next_weekday(1).isoformat()

    # Turn 1: the model looks up Tuesday and offers 4:00 PM.
    ai.then(call("get_available_slots", dates=[tue]), say("El martes tengo 4:00 PM. ¿Te funciona?"))
    await turn("quiero cita el martes en la tarde")
    state = (await env["session"]()).state
    assert f"{tue}T16:00" in {s.slot_id for s in state.offered_slots}

    # Turn 2: prepare — validated, summarized by code, NOT booked.
    ai.then(
        call("prepare_booking", slot_id=f"{tue}T16:00", for_self=True, reason="dolor de espalda"),
        lambda results: say(results[0]["summary"] + " ¿Lo confirmas?"),
    )
    reply = await turn("sí, a las 4")
    assert "4:00 PM" in reply
    assert await env["appointments"]() == []
    assert (await env["session"]()).state.draft is not None

    # Turn 3: confirm — exactly the drafted slot is written.
    ai.then(call("confirm_booking"), say("Listo, tu cita quedó agendada para el martes a las 4:00 PM."))
    reply = await turn("sí confírmala")
    appts = await env["appointments"]()
    assert len(appts) == 1
    assert appts[0].start_datetime.astimezone(now_mx().tzinfo).strftime("%Y-%m-%dT%H:%M") == f"{tue}T16:00"
    state = (await env["session"]()).state
    assert state.draft is None
    assert state.recent_actions[-1].ok and "book" in state.recent_actions[-1].claims
    assert "quedó agendada" in reply  # backed by confirm_booking: no correction


async def test_reschedule_moves_through_a_draft(env):
    ai, turn = env["ai"], env["turn"]
    tue, wed = next_weekday(1).isoformat(), next_weekday(2).isoformat()
    ai.then(
        call("prepare_booking", slot_id=f"{tue}T09:00", for_self=True, reason="chequeo"),
        say("¿Confirmas?"), call("confirm_booking"), say("Agendada para el martes a las 9:00 AM."),
    )
    await turn("cita martes 9")
    await turn("sí")
    original = (await env["appointments"]())[0]

    ai.then(
        call("prepare_booking", slot_id=f"{wed}T09:50", for_self=True,
             replaces_appointment_id=str(original.id)),
        lambda results: say(results[0]["summary"] + " ¿Confirmas el cambio?"),
        call("confirm_booking"),
        say("Tu cita quedó reagendada para el miércoles a las 9:50 AM."),
    )
    await turn("muévela al miércoles")
    await turn("sí")
    by_id = {a.id: a for a in await env["appointments"]()}
    assert by_id[original.id].status == "cancelled"
    moved = [a for a in by_id.values() if a.rescheduled_from == original.id]
    assert len(moved) == 1 and moved[0].status == "scheduled"


async def test_taken_slot_is_refused_at_prepare_time(env):
    ai, turn = env["ai"], env["turn"]
    thu = next_weekday(3).isoformat()
    ai.then(
        call("prepare_booking", slot_id=f"{thu}T09:00", for_self=True, reason="chequeo"),
        say("¿Confirmas?"), call("confirm_booking"), say("Agendada para el jueves a las 9:00 AM."),
    )
    await turn("cita jueves 9")
    await turn("sí")

    # A different patient can't be drafted onto the same slot.
    ai.then(
        call("prepare_booking", slot_id=f"{thu}T09:00", for_self=False,
             patient_name="Ana López", patient_phone="5512345678", reason="chequeo"),
        lambda results: say("Ese horario ya está ocupado." if "error" in results[0] else "¿Confirmas?"),
    )
    reply = await turn("y otra para mi novia a la misma hora")
    assert reply == "Ese horario ya está ocupado."
    assert (await env["session"]()).state.draft is None


async def test_unbacked_claim_is_corrected_before_sending(env):
    ai, turn = env["ai"], env["turn"]
    ai.then(say("Listo, ya cancelé tu cita."), say("¿Cuál de tus citas quieres cancelar?"))
    reply = await turn("cancela mi cita")
    assert reply == "¿Cuál de tus citas quieres cancelar?"

    async with get_async_session_maker()() as db:
        trace = (await db.execute(
            select(AiTurnTrace).where(AiTurnTrace.office_id == env["office"].id)
            .order_by(AiTurnTrace.created_at.desc())
        )).scalars().first()
    assert trace.outcome == "ok"
    assert [v["kind"] for v in trace.grounding_violations] == ["claimed_action"]
    assert trace.reply == reply


async def test_availability_finds_next_free_day_and_filters_part_of_day(env):
    from datetime import datetime

    from app.core.constants import MX_TIMEZONE
    from app.db.models import TimeBlock
    from app.modules.ai.tool_helpers import availability_for_dates

    office = env["office"]
    tue = next_weekday(1)
    async with get_async_session_maker()() as db:
        db.add(TimeBlock(
            office_id=office.id,
            start_date=datetime.combine(tue, datetime.min.time(), tzinfo=MX_TIMEZONE),
            end_date=datetime.combine(tue, datetime.max.time(), tzinfo=MX_TIMEZONE),
            reason="Congreso", is_all_day=True, origin="manual",
        ))
        await db.commit()

        result = await availability_for_dates(office.id, [tue.isoformat()], db, slot_minutes=40)
        assert result["days"][0]["slots"] == []
        nxt = result["next_available"]
        assert nxt["date"] == (tue + timedelta(days=1)).isoformat()
        assert nxt["slots"][0] == {"slot_id": f"{nxt['date']}T09:00", "label": "9:00 AM", "period": "mañana"}

        wed = (tue + timedelta(days=1)).isoformat()
        afternoon = await availability_for_dates(office.id, [wed], db, slot_minutes=40, part_of_day="tarde")
        # "tarde" starts at noon, as in "buenas tardes".
        assert [s["label"] for s in afternoon["days"][0]["slots"]] == [
            "12:20 PM", "1:10 PM", "4:00 PM", "4:50 PM", "5:40 PM",
        ]


async def test_calendar_failure_is_not_reported_as_no_slots(env, monkeypatch):
    from app.modules.ai import tool_helpers

    async def broken(*args, **kwargs):
        raise RuntimeError("google freebusy timeout")

    monkeypatch.setattr(tool_helpers, "compute_day_availability", broken)
    async with get_async_session_maker()() as db:
        result = await tool_helpers.availability_for_dates(
            env["office"].id, [next_weekday(1).isoformat()], db
        )
    assert result["error_kind"] == "calendar_unavailable"
    assert "days" not in result


async def test_past_date_is_refused(env):
    from app.modules.ai.tool_helpers import availability_for_dates

    yesterday = (now_mx().date() - timedelta(days=1)).isoformat()
    async with get_async_session_maker()() as db:
        result = await availability_for_dates(env["office"].id, [yesterday], db)
    assert "ya pasó" in result["error"]


async def test_draft_cannot_be_confirmed_in_the_turn_it_was_prepared(env):
    ai, turn = env["ai"], env["turn"]
    tue = next_weekday(1).isoformat()
    ai.then(
        call("prepare_booking", slot_id=f"{tue}T09:00", for_self=True, reason="chequeo"),
        call("confirm_booking"),
        lambda results: say(
            "¿Te confirmo el martes a las 9:00 AM?" if "error" in results[0] else "Agendada."
        ),
    )
    reply = await turn("cita el martes a las 9")
    assert reply == "¿Te confirmo el martes a las 9:00 AM?"
    assert await env["appointments"]() == []
    assert (await env["session"]()).state.draft is not None


async def test_off_grid_time_is_refused_with_nearest_slots(env):
    # First visit = 40 min + 10 buffer: the grid is 9:00, 9:50, 10:40…; 10:00 is
    # free but not offered, and booking it would kill the 9:50 slot.
    ai, turn = env["ai"], env["turn"]
    fri = next_weekday(4).isoformat()
    ai.then(
        call("prepare_booking", slot_id=f"{fri}T10:00", for_self=True, reason="dolor"),
        lambda results: say(", ".join(s["label"] for s in results[0]["nearest_slots"])),
    )
    reply = await turn("el viernes a las 10")
    assert reply == "9:00 AM, 9:50 AM, 10:40 AM"
    assert (await env["session"]()).state.draft is None


async def test_patient_words_are_resolved_by_code(env):
    from app.modules.ai.tools import ToolContext, execute_tool
    from app.modules.conversation.state import ConversationState

    async with get_async_session_maker()() as db:
        office = await db.get(type(env["office"]), env["office"].id)
        ctx = ToolContext(db=db, office=office, patient_id=None, whatsapp_id=PATIENT,
                          redis_client=None, state=ConversationState())
        # "el miércoles" is always the next Wednesday — never the one after.
        result = await execute_tool("get_available_slots", {"when": "el miércoles en la mañana"}, ctx)
        wed = next_weekday(2)
        assert result["interpreted"]["dates"] == [wed.isoformat()]
        assert result["interpreted"]["part_of_day"] == "mañana"
        assert all(s["period"] == "mañana" for s in result["days"][0]["slots"])

        # Unreadable words: ask, don't guess.
        result = await execute_tool("get_available_slots", {"when": "cuando se pueda"}, ctx)
        assert "error" in result and "Pregúntale" in result["next_step"]


async def test_ambiguous_words_return_options(env):
    from app.modules.ai.tools import ToolContext, execute_tool
    from app.modules.conversation.state import ConversationState

    today_name = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"][now_mx().weekday()]
    async with get_async_session_maker()() as db:
        office = await db.get(type(env["office"]), env["office"].id)
        ctx = ToolContext(db=db, office=office, patient_id=None, whatsapp_id=PATIENT,
                          redis_client=None, state=ConversationState())
        result = await execute_tool("get_available_slots", {"when": f"el {today_name}"}, ctx)
    assert result["ambiguous_date"] == f"el {today_name}"
    assert len(result["options"]) == 2
