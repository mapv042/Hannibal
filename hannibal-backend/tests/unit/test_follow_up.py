"""The one follow-up: when it is armed, when it is dropped, what it says."""

import uuid
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from app.core.constants import MX_TIMEZONE
from app.modules.conversation import follow_up
from app.modules.conversation.follow_up import (
    FOLLOW_UP_DELAY,
    next_sending_time,
    pending_kind,
    schedule_after_turn,
)
from app.modules.conversation.slot_options import present
from app.modules.conversation.state import BookingDraft, ConversationState, OfferedSlot

NOW = datetime(2026, 9, 21, 12, 7, tzinfo=MX_TIMEZONE)  # Monday noon
THU = "jueves 24 de septiembre"
SLOTS = [
    OfferedSlot(slot_id="2026-09-24T16:00", date_label=THU, time_label="4:00 PM"),
    OfferedSlot(slot_id="2026-09-24T17:00", date_label=THU, time_label="5:00 PM"),
]
WITH_BUTTONS = "¿Cuál te acomoda? [[2026-09-24T16:00]] [[2026-09-24T17:00]]"


def draft(created_at, slot_id="2026-09-24T16:00", replaces=None):
    return BookingDraft(
        slot_id=slot_id,
        label="jueves 24 de septiembre a las 4:00 PM",
        summary="…",
        patient_name="Ana López",
        reason="Chequeo",
        replaces_appointment_id=replaces,
        created_at=created_at.isoformat(),
    )


def ctx(state=None, booked=(), started=NOW - timedelta(seconds=5)):
    return SimpleNamespace(
        state=state or ConversationState(offered_slots=list(SLOTS)),
        booked_appointment_ids=list(booked),
        turn_started_at=started,
    )


# ---------------------------------------------------------------- pending?


def test_slots_offered_this_turn_are_pending():
    assert pending_kind(present(WITH_BUTTONS, SLOTS), ctx()) == "slots"


def test_a_summary_shown_this_turn_is_pending():
    state = ConversationState(draft=draft(NOW))
    assert pending_kind(present("¿Confirmo?", SLOTS), ctx(state)) == "draft"


def test_an_old_summary_is_not_pending():
    state = ConversationState(draft=draft(NOW - timedelta(hours=1)))
    assert pending_kind(present("Claro, aquí estoy.", SLOTS), ctx(state)) is None


def test_nothing_offered_is_not_pending():
    assert pending_kind(present("Cuesta $800.", SLOTS), ctx()) is None


def test_a_booking_this_turn_settles_it():
    assert pending_kind(present(WITH_BUTTONS, SLOTS), ctx(booked=[uuid.uuid4()])) is None


# ---------------------------------------------------------------- arming


@pytest.fixture
def facts(monkeypatch):
    state = {"messages": 4, "active": []}

    async def count(db, conversation_id):
        return state["messages"]

    async def active(db, office_id, patient_id, now):
        return list(state["active"])

    monkeypatch.setattr(follow_up, "_message_count", count)
    monkeypatch.setattr(follow_up, "_active_appointment_ids", active)
    return state


def conversation(**kw):
    base = dict(
        id=uuid.uuid4(),
        whatsapp_id="5215550000001",
        patient_id=uuid.uuid4(),
        follow_up_due_at=None,
        follow_up_sent_at=None,
        follow_up_context=None,
    )
    base.update(kw)
    return SimpleNamespace(**base)


def office(**kw):
    base = dict(
        id=uuid.uuid4(), follow_up_enabled=True, assistant_tone="casual",
        whatsapp_phone_id="pnid", whatsapp_token="tok",
    )
    base.update(kw)
    return SimpleNamespace(**base)


async def test_armed_three_hours_out_with_what_was_pending(facts):
    conv = conversation()
    await schedule_after_turn(None, office(), conv, present(WITH_BUTTONS, SLOTS), ctx(), NOW)
    assert conv.follow_up_due_at == NOW + FOLLOW_UP_DELAY
    assert conv.follow_up_context == {
        "kind": "slots",
        "armed_on": "2026-09-21",
        "slot_ids": ["2026-09-24T16:00", "2026-09-24T17:00"],
        "message_count": 4,
        "active_appointment_ids": [],
    }


async def test_a_turn_with_nothing_pending_clears_it(facts):
    conv = conversation(follow_up_due_at=NOW, follow_up_context={"kind": "slots"})
    await schedule_after_turn(None, office(), conv, present("Cuesta $800.", SLOTS), ctx(), NOW)
    assert conv.follow_up_due_at is None and conv.follow_up_context is None


async def test_one_per_day_even_after_a_new_offer(facts):
    conv = conversation(follow_up_sent_at=NOW - timedelta(hours=5))
    await schedule_after_turn(None, office(), conv, present(WITH_BUTTONS, SLOTS), ctx(), NOW)
    assert conv.follow_up_due_at is None


async def test_a_day_later_it_can_be_armed_again(facts):
    conv = conversation(follow_up_sent_at=NOW - timedelta(hours=25))
    await schedule_after_turn(None, office(), conv, present(WITH_BUTTONS, SLOTS), ctx(), NOW)
    assert conv.follow_up_due_at is not None


@pytest.mark.parametrize("hour, armed", [(18, True), (19, False), (22, False)])
async def test_not_armed_when_it_could_only_go_out_tomorrow(facts, hour, armed):
    # Sending closes at 21:00: pending at 19:00 would be due at 21:00 — too late.
    conv = conversation()
    at = NOW.replace(hour=hour, minute=0)
    await schedule_after_turn(None, office(), conv, present(WITH_BUTTONS, SLOTS), ctx(started=at), at)
    assert (conv.follow_up_due_at is not None) == armed


async def test_an_office_can_turn_it_off(facts):
    conv = conversation()
    await schedule_after_turn(
        None, office(follow_up_enabled=False), conv, present(WITH_BUTTONS, SLOTS), ctx(), NOW
    )
    assert conv.follow_up_due_at is None


async def test_the_draft_slot_goes_first(facts):
    conv = conversation()
    state = ConversationState(offered_slots=list(SLOTS), draft=draft(NOW, slot_id="2026-09-24T17:00"))
    await schedule_after_turn(None, office(), conv, present(WITH_BUTTONS, SLOTS), ctx(state), NOW)
    assert conv.follow_up_context["kind"] == "draft"
    assert conv.follow_up_context["slot_ids"] == ["2026-09-24T17:00", "2026-09-24T16:00"]


# ---------------------------------------------------------------- sending window


@pytest.mark.parametrize("at, expected", [
    ((12, 7), (0, 12, 7)),
    ((6, 30), (0, 8, 0)),
    ((23, 7), (1, 8, 0)),
])
def test_next_sending_time(at, expected):
    t = NOW.replace(hour=at[0], minute=at[1])
    days, h, m = expected
    assert next_sending_time(t) == (NOW + timedelta(days=days)).replace(hour=h, minute=m)


# ---------------------------------------------------------------- the sweep, one conversation


class Redis:
    def __init__(self, busy=False):
        self.busy = busy

    async def exists(self, key):
        return 1 if self.busy else 0


class Client:
    def __init__(self):
        self.sent = []

    async def send_interactive_buttons(self, **kw):
        self.sent.append(("buttons", kw))
        return "wamid.b"

    async def send_interactive_list(self, **kw):
        self.sent.append(("list", kw))
        return "wamid.l"

    async def send_text_message(self, **kw):
        self.sent.append(("text", kw))
        return "wamid.t"


class DB:
    def __init__(self):
        self.added = []

    def add(self, obj):
        self.added.append(obj)


@pytest.fixture
def world(monkeypatch, facts):
    w = SimpleNamespace(
        paused=False, taken=None, last_inbound=NOW - timedelta(hours=3), urgency=False,
        taken_slots=set(), session=SimpleNamespace(
            state=ConversationState(offered_slots=list(SLOTS)),
            claude_history=[], patient_id=None,
        ),
        saved=[],
    )

    async def check_pause(office_id, redis):
        return w.paused

    async def taken_until(office_id, whatsapp_id, redis):
        return w.taken

    async def last_inbound(db, office_id, whatsapp_id):
        return w.last_inbound

    async def urgency(db, office_id, whatsapp_id):
        return w.urgency

    async def duration(db, office, patient_id):
        return 30, "first_visit"

    async def bookable(office_id, start, end, db, **kw):
        return "taken" if start.strftime("%Y-%m-%dT%H:%M") in w.taken_slots else None

    async def greeting(db, patient_id):
        return "Hola Ana,"

    class Store:
        def __init__(self, redis_client=None):
            pass

        async def get_session(self, whatsapp_id, office_id):
            return w.session

        async def save_session(self, whatsapp_id, office_id, session):
            w.saved.append(session)

    monkeypatch.setattr(follow_up, "check_pause", check_pause)
    monkeypatch.setattr(follow_up, "conversation_taken_until", taken_until)
    monkeypatch.setattr(follow_up, "last_inbound_at", last_inbound)
    monkeypatch.setattr(follow_up, "_urgency_pending", urgency)
    monkeypatch.setattr(follow_up, "resolve_appointment_duration", duration)
    monkeypatch.setattr(follow_up, "check_slot_bookable", bookable)
    monkeypatch.setattr(follow_up, "_greeting", greeting)
    monkeypatch.setattr(follow_up, "SessionStore", Store)
    return w


def armed(kind="slots", slot_ids=("2026-09-24T16:00", "2026-09-24T17:00"), **kw):
    return conversation(
        follow_up_due_at=NOW + FOLLOW_UP_DELAY,
        follow_up_context={
            "kind": kind, "armed_on": NOW.date().isoformat(), "slot_ids": list(slot_ids),
            "message_count": 4, "active_appointment_ids": [],
        },
        **kw,
    )


SEND_AT = NOW + FOLLOW_UP_DELAY + timedelta(minutes=8)  # the sweep at 14:15


async def run(conv, world, client=None, redis=None, office_=None):
    client = client or Client()
    db = DB()
    outcome = await follow_up._follow_up(
        db, redis or Redis(), client, office_ or office(), conv, SEND_AT
    )
    return outcome, client, db


async def test_sends_the_slots_still_free_as_buttons(world):
    conv = armed()
    outcome, client, db = await run(conv, world)
    assert outcome == "sent"
    kind, kw = client.sent[0]
    assert kind == "buttons"
    assert kw["body_text"] == "Hola Ana, ¿te aparto alguno de estos horarios? Siguen libres:"
    assert [b["id"] for b in kw["buttons"]] == ["slot:2026-09-24T16:00", "slot:2026-09-24T17:00"]
    # Cleared, with the day's limit started, and remembered by the model.
    assert conv.follow_up_due_at is None and conv.follow_up_sent_at == SEND_AT
    assert db.added[0].extra_metadata["source"] == "follow_up"
    assert "4:00 PM y 5:00 PM" in world.saved[0].claude_history[-1]["content"]


async def test_a_taken_slot_is_left_out(world):
    world.taken_slots = {"2026-09-24T16:00"}
    _, client, _ = await run(armed(), world)
    kw = client.sent[0][1]
    assert kw["body_text"].endswith("¿te aparto este horario? Sigue libre:")
    assert [b["id"] for b in kw["buttons"]] == ["slot:2026-09-24T17:00"]


async def test_nothing_is_sent_when_every_slot_was_taken(world):
    world.taken_slots = {"2026-09-24T16:00", "2026-09-24T17:00"}
    conv = armed()
    outcome, client, _ = await run(conv, world)
    assert outcome == "slots_taken" and client.sent == [] and conv.follow_up_due_at is None


async def test_a_pending_summary_asks_to_confirm_it(world):
    world.session.state.draft = draft(NOW)
    outcome, client, _ = await run(armed(kind="draft"), world)
    kind, kw = client.sent[0]
    assert outcome == "sent" and kind == "buttons"
    assert kw["body_text"] == "Hola Ana, ¿confirmo tu cita del jueves 24 de septiembre a las 4:00 PM?"
    assert [b["title"] for b in kw["buttons"]] == ["Sí, confirmar", "No, gracias"]


async def test_a_pending_move_asks_to_confirm_the_move(world):
    world.session.state.draft = draft(NOW, replaces=str(uuid.uuid4()))
    _, client, _ = await run(armed(kind="draft"), world)
    assert "¿confirmo el cambio de tu cita al jueves 24" in client.sent[0][1]["body_text"]


async def test_a_summary_whose_slot_was_taken_offers_the_rest(world):
    world.session.state.draft = draft(NOW)
    world.taken_slots = {"2026-09-24T16:00"}
    _, client, _ = await run(armed(kind="draft"), world)
    assert [b["id"] for b in client.sent[0][1]["buttons"]] == ["slot:2026-09-24T17:00"]


async def test_formal_offices_say_usted(world):
    _, client, _ = await run(armed(), world, office_=office(assistant_tone="formal"))
    assert "¿le aparto" in client.sent[0][1]["body_text"]


@pytest.mark.parametrize("change, outcome", [
    (lambda w, f: f.update(messages=5), "conversation_moved_on"),
    (lambda w, f: setattr(w, "paused", True), "doctor_handling"),
    (lambda w, f: setattr(w, "taken", NOW), "doctor_handling"),
    (lambda w, f: setattr(w, "last_inbound", NOW - timedelta(hours=24)), "window_closed"),
    (lambda w, f: setattr(w, "session", None), "no_session"),
    (lambda w, f: f.update(active=["new-cita"]), "booked_elsewhere"),
    (lambda w, f: setattr(w, "urgency", True), "urgency_pending"),
])
async def test_dropped_when_something_happened(world, facts, change, outcome):
    change(world, facts)
    conv = armed()
    got, client, _ = await run(conv, world)
    assert got == outcome and client.sent == []
    assert conv.follow_up_due_at is None  # retired, never retried


async def test_a_turn_in_flight_leaves_it_for_the_turn(world):
    conv = armed()
    outcome, client, _ = await run(conv, world, redis=Redis(busy=True))
    assert outcome == "busy" and client.sent == [] and conv.follow_up_due_at is not None


async def test_disabled_office_drops_it(world):
    conv = armed()
    outcome, _, _ = await run(conv, world, office_=office(follow_up_enabled=False))
    assert outcome == "disabled" and conv.follow_up_due_at is None


async def test_the_next_day_it_is_dropped(world):
    # The worker was down overnight: yesterday's offer is not followed up.
    conv = armed()
    tomorrow = SEND_AT + timedelta(days=1)
    world.last_inbound = tomorrow - timedelta(hours=3)  # window still open
    out, client, _ = await run_at(conv, world, tomorrow)
    assert out == "next_day" and client.sent == [] and conv.follow_up_due_at is None


async def test_after_the_sending_window_it_is_dropped_not_deferred(world):
    conv = armed()
    world.last_inbound = SEND_AT.replace(hour=20)
    out, _, _ = await run_at(conv, world, SEND_AT.replace(hour=21, minute=15))
    assert out == "next_day" and conv.follow_up_due_at is None


async def test_before_the_window_opens_it_waits_the_same_day(world):
    early = NOW.replace(hour=5, minute=30)
    conv = armed()
    conv.follow_up_context["armed_on"] = early.date().isoformat()
    world.last_inbound = early
    out, _, _ = await run_at(conv, world, early + FOLLOW_UP_DELAY)
    assert out == "deferred" and conv.follow_up_due_at is not None


async def test_rows_armed_before_armed_on_existed_use_their_due_time(world):
    conv = armed()
    del conv.follow_up_context["armed_on"]
    out, _, _ = await run_at(conv, world, SEND_AT + timedelta(days=1))
    assert out == "next_day"


async def run_at(conv, world, at):
    client = Client()
    out = await follow_up._follow_up(DB(), Redis(), client, office(), conv, at)
    return out, client, None
