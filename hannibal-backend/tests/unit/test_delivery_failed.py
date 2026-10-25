"""A doctor message that Meta fails to deliver reaches the doctor (ARGOS P21, P43)."""

import uuid
from types import SimpleNamespace

from app.modules.whatsapp import doctor_notify
from app.modules.whatsapp import router


class _Result:
    def __init__(self, row):
        self.row = row

    def scalar_one_or_none(self):
        return self.row

    def scalars(self):
        return SimpleNamespace(first=lambda: self.row)


class _DB:
    def __init__(self, msg, conversation, patient):
        self.results = [msg, patient]
        self.conversation = conversation

    async def execute(self, stmt):
        return _Result(self.results.pop(0))

    async def get(self, model, key):
        return self.conversation

    async def commit(self):
        pass


def _failed(message_id):
    return {
        "id": message_id,
        "status": "failed",
        "recipient_id": "5215500000000",
        "errors": [{"code": 131049, "title": "This message was not delivered"}],
    }


async def _run(monkeypatch, *, source, previous_status="sent"):
    office = SimpleNamespace(id=uuid.uuid4())
    msg = SimpleNamespace(
        whatsapp_message_id="wamid.1",
        delivery_status=previous_status,
        extra_metadata={"source": source},
        conversation_id=uuid.uuid4(),
        content="Llegue 10 minutos antes,\npor favor.",
    )
    conversation = SimpleNamespace(whatsapp_id="5215500000000")
    patient = SimpleNamespace(name="Ana Prueba")
    alerts = []

    async def fake_alert(redis_client, meta_client, office, **kwargs):
        alerts.append(kwargs)
        return "notified"

    monkeypatch.setattr(doctor_notify, "send_doctor_alert", fake_alert)
    monkeypatch.setattr(router, "get_meta_client", lambda: object())

    await router._process_status(_failed("wamid.1"), office, _DB(msg, conversation, patient), None)
    return msg, alerts


async def test_failed_doctor_message_is_reported_to_the_doctor(monkeypatch):
    msg, alerts = await _run(monkeypatch, source="doctor_send_message")

    assert msg.delivery_status == "failed"
    assert len(alerts) == 1
    assert "Ana Prueba" in alerts[0]["text"]
    assert "Llegue 10 minutos antes, por favor." in alerts[0]["text"]
    assert alerts[0]["template_name"] is None


async def test_repeated_failure_webhook_does_not_notify_twice(monkeypatch):
    _, alerts = await _run(monkeypatch, source="doctor_send_message", previous_status="failed")
    assert alerts == []


async def test_other_failed_messages_do_not_notify_the_doctor(monkeypatch):
    _, alerts = await _run(monkeypatch, source="reminder_task")
    assert alerts == []
