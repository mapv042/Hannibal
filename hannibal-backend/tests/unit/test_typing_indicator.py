"""Blue ticks + "escribiendo…": only for a batch the assistant will answer."""

import asyncio
from types import SimpleNamespace

import pytest

from app.modules.whatsapp import router as wa_router


class RecordingClient:
    def __init__(self, fail=False, hang=False):
        self.calls, self.fail, self.hang = [], fail, hang

    async def mark_as_read(self, **kwargs):
        self.calls.append(kwargs)
        if self.hang:
            await asyncio.sleep(10)
        if self.fail:
            raise RuntimeError("meta down")
        return True


def office(**overrides):
    base = dict(
        id="office-1",
        whatsapp_phone_id="pnid",
        whatsapp_token="tok",
        owner_phone="5215550000099",
        secondary_owner_phone=None,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def msg(i):
    return {"id": f"m{i}", "from": "5215550000001", "type": "text", "text": {"body": str(i)}}


async def test_marks_the_newest_message_with_typing():
    client = RecordingClient()
    await wa_router._acknowledge(client, office(), [msg(1), msg(2), msg(3)])
    assert client.calls == [
        {"phone_number_id": "pnid", "token": "tok", "message_id": "m3", "typing_indicator": True}
    ]


async def test_failure_never_reaches_the_turn():
    await wa_router._acknowledge(RecordingClient(fail=True), office(), [msg(1)])


async def test_a_hung_meta_call_does_not_hold_the_answer(monkeypatch):
    monkeypatch.setattr(wa_router, "ACK_TIMEOUT_SECONDS", 0.01)
    await asyncio.wait_for(
        wa_router._acknowledge(RecordingClient(hang=True), office(), [msg(1)]), timeout=1
    )


async def test_skipped_without_whatsapp_credentials():
    client = RecordingClient()
    await wa_router._acknowledge(client, office(whatsapp_token=None), [msg(1)])
    assert client.calls == []


@pytest.fixture
def routing(monkeypatch):
    client = RecordingClient()
    processed = []

    class FakeManager:
        def __init__(self, *args):
            pass

        async def process(self, office, messages, db):
            processed.append([m["id"] for m in messages])

    async def not_paused(*args):
        return False

    async def not_taken(*args):
        return None

    async def persist(*args):
        pass

    monkeypatch.setattr(wa_router, "get_meta_client", lambda: client)
    monkeypatch.setattr(wa_router, "ConversationManager", FakeManager)
    monkeypatch.setattr(wa_router, "DoctorConversationManager", FakeManager)
    monkeypatch.setattr(wa_router, "SessionStore", lambda redis: None)
    monkeypatch.setattr(wa_router, "check_pause", not_paused)
    monkeypatch.setattr(wa_router, "conversation_taken_until", not_taken)
    monkeypatch.setattr(wa_router, "_persist_incoming_while_paused", persist)
    return client, processed


async def test_patient_turn_is_acknowledged_before_processing(routing):
    client, processed = routing
    await wa_router._route_message([msg(1)], office(), db=None, redis_client=None)
    assert [c["message_id"] for c in client.calls] == ["m1"]
    assert processed == [["m1"]]


async def test_doctor_turn_is_acknowledged(routing):
    client, processed = routing
    doctor_msg = {**msg(1), "from": "5215550000099"}
    await wa_router._route_message([doctor_msg], office(), db=None, redis_client=None)
    assert [c["message_id"] for c in client.calls] == ["m1"]


async def test_no_blue_ticks_while_the_bot_is_paused(routing, monkeypatch):
    client, processed = routing

    async def paused(*args):
        return True

    monkeypatch.setattr(wa_router, "check_pause", paused)
    await wa_router._route_message([msg(1)], office(), db=None, redis_client=None)
    assert client.calls == [] and processed == []


async def test_no_blue_ticks_when_the_doctor_took_the_thread(routing, monkeypatch):
    client, processed = routing

    async def taken(*args):
        return "2026-11-01T12:00:00"

    monkeypatch.setattr(wa_router, "conversation_taken_until", taken)
    await wa_router._route_message([msg(1)], office(), db=None, redis_client=None)
    assert client.calls == [] and processed == []
