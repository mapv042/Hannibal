"""Google rejecting an office's credentials: skip, flag, tell the doctor once."""

import uuid
from types import SimpleNamespace

import httpx
import pytest

from app.core.exceptions import GoogleCalendarAuthError
from app.modules.google_calendar import connection


class FakeRedis:
    def __init__(self):
        self.kv = {}

    async def get(self, k):
        return self.kv.get(k)

    async def setex(self, k, ttl, v):
        self.kv[k] = v

    async def set(self, k, v, nx=False, ex=None):
        if nx and k in self.kv:
            return None
        self.kv[k] = v
        return True

    async def delete(self, k):
        self.kv.pop(k, None)


def test_report_skips_google_and_enqueues_once(monkeypatch):
    office_id = uuid.uuid4()
    queued = []
    monkeypatch.setattr(connection, "dispatch", lambda task, args, **kw: queued.append(args))
    assert not connection.should_skip_google(office_id)
    connection.report_auth_failure(office_id, GoogleCalendarAuthError())
    connection.report_auth_failure(office_id, GoogleCalendarAuthError())  # within the window
    assert connection.should_skip_google(office_id)
    assert queued == [[str(office_id)]]
    connection.clear_local_skip(office_id)


async def test_doctor_is_told_once_a_day(monkeypatch):
    office_id = uuid.uuid4()
    sent = []

    async def fake_alert(redis, meta, office, *, text, template_name, template_params, log_event):
        sent.append((text, template_name))
        return "notified"

    import app.modules.whatsapp.doctor_notify as dn
    monkeypatch.setattr(dn, "send_doctor_alert", fake_alert)

    class DB:
        async def get(self, model, id_):
            return SimpleNamespace(id=office_id)

    redis = FakeRedis()
    first = await connection.mark_disconnected_and_notify(DB(), redis, None, office_id)
    second = await connection.mark_disconnected_and_notify(DB(), redis, None, office_id)
    assert (first, second) == ("notified", "already_alerted")
    assert len(sent) == 1 and "Reconéctalo" in sent[0][0]
    assert sent[0][1] == "doctor_calendar_disconnected"
    assert await connection.is_disconnected(redis, office_id)

    await connection.mark_reconnected(redis, office_id)
    assert not await connection.is_disconnected(redis, office_id)


@pytest.mark.parametrize("status,expected", [
    (400, GoogleCalendarAuthError),   # invalid_grant: revoked / expired
    (401, GoogleCalendarAuthError),
    (503, None),                      # transient: plain GoogleCalendarError
])
async def test_refresh_failure_is_typed(monkeypatch, status, expected):
    from app.core.exceptions import GoogleCalendarError
    from app.modules.google_calendar import auth

    transport = httpx.MockTransport(lambda req: httpx.Response(status, json={"error": "invalid_grant"}))
    real = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: real(transport=transport))

    class DB:
        async def get(self, model, id_):
            return SimpleNamespace(google_calendar_token={"refresh_token": "r"})

    with pytest.raises(GoogleCalendarError) as exc:
        await auth.refresh_google_token(uuid.uuid4(), DB())
    if expected:
        assert isinstance(exc.value, expected)
    else:
        assert not isinstance(exc.value, GoogleCalendarAuthError)
