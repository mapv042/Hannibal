"""A repeated "sí, mándalo" must not send the same message twice."""

import uuid
from types import SimpleNamespace

from app.modules.ai import doctor_tools as dt


class FakeRedis:
    def __init__(self):
        self.kv = {}

    async def get(self, k):
        return self.kv.get(k)

    async def setex(self, k, ttl, v):
        self.kv[k] = v


async def test_identical_message_is_sent_once(monkeypatch):
    patient_id = uuid.uuid4()
    office = SimpleNamespace(id=uuid.uuid4())
    patient = SimpleNamespace(id=patient_id, office_id=office.id, whatsapp_id="521", name="Juan")
    sent = []

    class DB:
        async def get(self, model, pid):
            return patient

    async def drafts(ctx):
        return {str(patient_id): {"patient_name": "Juan", "message": "Trae tus estudios."}}

    async def clear(ctx):
        return None

    async def send(ctx, p, message):
        sent.append(message)
        return "wamid"

    monkeypatch.setattr(dt, "_load_message_drafts", drafts)
    monkeypatch.setattr(dt, "_clear_message_drafts", clear)
    monkeypatch.setattr(dt, "_send_patient_message", send)
    ctx = SimpleNamespace(office=office, db=DB(), redis_client=FakeRedis())

    first = await dt._handle_confirm_send_messages({"approved": True}, ctx)
    second = await dt._handle_confirm_send_messages({"approved": True}, ctx)

    assert sent == ["Trae tus estudios."]
    assert first["sent_to"] == ["Juan"]
    assert second["already_sent"] == ["Juan"] and "error" not in second
