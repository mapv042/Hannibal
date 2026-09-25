"""What the doctor reads on a cancelled event in Google Calendar."""

from datetime import datetime

import httpx

from app.core.constants import MX_TIMEZONE
from app.modules.google_calendar import service as gcal
from app.modules.google_calendar.sync import calendar_cancellation_note


def test_cancellation_note_with_reason():
    note = calendar_cancellation_note("el paciente", reason="le  surgió\n  trabajo")
    assert note.startswith("Cancelada por el paciente el ")
    assert note.endswith("Motivo: le surgió trabajo")  # whitespace collapsed


def test_cancellation_note_without_reason():
    assert "Motivo" not in calendar_cancellation_note("el doctor")


def test_reschedule_note_says_where_it_went():
    note = calendar_cancellation_note(
        "el paciente", moved_to=datetime(2026, 10, 1, 16, 50, tzinfo=MX_TIMEZONE)
    )
    assert note.startswith("Reagendada por el paciente el ")
    assert note.endswith("al jueves 1 de octubre a las 4:50 PM.")


def test_long_reason_is_capped():
    assert len(calendar_cancellation_note("el paciente", reason="x" * 1000)) < 300


async def test_mark_event_cancelled_appends_note_once(monkeypatch):
    patches = []
    event = {"summary": "Cita: Juan", "description": "Motivo: chequeo\nAgendada por WhatsApp"}

    def handler(request):
        if request.method == "GET":
            return httpx.Response(200, json=dict(event))
        body = __import__("json").loads(request.content)
        patches.append(body)
        event.update({k: v for k, v in body.items() if k in ("summary", "description")})
        return httpx.Response(200, json={})

    transport = httpx.MockTransport(handler)
    real_client = httpx.AsyncClient
    monkeypatch.setattr(gcal.httpx, "AsyncClient", lambda **kw: real_client(transport=transport))

    async def token(*a):
        return "t"

    class DB:
        async def get(self, model, id_):
            return type("O", (), {"google_calendar_id": "cal"})()

    monkeypatch.setattr(gcal, "get_valid_google_token", token, raising=False)
    import app.modules.google_calendar.auth as auth
    monkeypatch.setattr(auth, "get_valid_google_token", token)

    note = "Cancelada por el paciente el 24/09/2026 a las 10:15 AM. Motivo: trabajo"
    await gcal.mark_event_cancelled("o", "ev", DB(), note=note)
    await gcal.mark_event_cancelled("o", "ev", DB(), note=note)  # a retry / the audit repair

    assert patches[0]["transparency"] == "transparent" and patches[0]["colorId"] == "11"
    assert patches[0]["description"].endswith(note)
    assert "description" not in patches[1]              # not appended twice
    assert patches[1]["summary"] == "[CANCELADA] Cita: Juan"  # title not doubled
