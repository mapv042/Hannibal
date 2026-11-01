"""Add-to-calendar: the signed link, the .ics it serves, and the button after a booking."""

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.core.exceptions import NotFoundError
from app.core.security import sign_link_value, verify_link_value
from app.modules.conversation.manager import ConversationManager
from app.modules.scheduling import calendar_file, calendar_router
from app.modules.scheduling.calendar_file import (
    CALENDAR_LINK_PURPOSE,
    build_ics,
    calendar_link,
    chain_root,
)

START = datetime(2026, 9, 24, 22, 0, tzinfo=timezone.utc)  # 4:00 PM in Mexico City


def office(**overrides):
    base = dict(
        id=uuid.uuid4(),
        name="Consultorio Dra. Núñez",
        address="Av. Insurgentes Sur 1234, Col. Del Valle; piso 3",
        whatsapp_phone="5215512345678",
        whatsapp_phone_id="pnid",
        whatsapp_token="tok",
        assistant_tone="casual",
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def appointment(office_id, **overrides):
    base = dict(
        id=uuid.uuid4(),
        office_id=office_id,
        start_datetime=START,
        end_datetime=START + timedelta(minutes=45),
        status="scheduled",
        rescheduled_from=None,
        consultation_reason="Dolor de rodilla",
    )
    base.update(overrides)
    return SimpleNamespace(**base)


# ---------------------------------------------------------------- signing


def test_signature_round_trip():
    sig = sign_link_value("appointment-ics", "abc")
    assert verify_link_value("appointment-ics", "abc", sig)
    assert not verify_link_value("appointment-ics", "abd", sig)


def test_signature_is_bound_to_its_purpose():
    sig = sign_link_value("appointment-ics", "abc")
    assert not verify_link_value("other-link", "abc", sig)


def test_non_ascii_signature_is_rejected_not_raised():
    assert not verify_link_value("appointment-ics", "abc", "ñandú")


def test_link_needs_a_backend_url(monkeypatch):
    monkeypatch.setattr(calendar_file.settings, "backend_url", "")
    assert calendar_link(uuid.uuid4()) is None


def test_link_points_at_the_public_endpoint(monkeypatch):
    monkeypatch.setattr(calendar_file.settings, "backend_url", "https://api.example.com/")
    appt_id = uuid.uuid4()
    url = calendar_link(appt_id)
    sig = sign_link_value(CALENDAR_LINK_PURPOSE, str(appt_id))
    assert url == f"https://api.example.com/api/public/calendar/{appt_id}/{sig}/cita.ics"


# ---------------------------------------------------------------- the file


def test_ics_has_the_cita_in_utc_and_no_patient_data():
    o = office()
    a = appointment(o.id)
    ics = build_ics(a, o, uid=a.id)
    unfolded = ics.replace("\r\n ", "")
    assert "DTSTART:20260924T220000Z" in unfolded
    assert "DTEND:20260924T224500Z" in unfolded
    assert f"UID:{a.id}@hannibal" in unfolded
    assert "Dolor de rodilla" not in unfolded  # the reason is health data
    assert "TRIGGER:-PT60M" in unfolded


def test_ics_escapes_text_and_uses_crlf():
    o = office()
    ics = build_ics(appointment(o.id), o, uid="x")
    unfolded = ics.replace("\r\n ", "")
    assert "LOCATION:Av. Insurgentes Sur 1234\\, Col. Del Valle\\; piso 3" in unfolded
    assert ics.endswith("\r\n")
    assert "\n" not in ics.replace("\r\n", "")


def test_long_lines_fold_without_splitting_accents():
    o = office(name="Clínica de Ortopedia y Traumatología Pediátrica del Niño Jesús, Querétaro")
    ics = build_ics(appointment(o.id), o, uid="x")
    for line in ics.split("\r\n"):
        assert len(line.encode("utf-8")) <= 75
        line.encode("utf-8").decode("utf-8")  # no broken character
    assert "Pediátrica del Niño Jesús" in ics.replace("\r\n ", "")


def test_falls_back_to_the_office_name_without_an_address():
    o = office(address=None, whatsapp_phone=None)
    unfolded = build_ics(appointment(o.id), o, uid="x").replace("\r\n ", "")
    assert "LOCATION:Consultorio Dra. Núñez" in unfolded
    assert "escribe al WhatsApp del consultorio." in unfolded


class ChainDB:
    def __init__(self, rows):
        self.rows = {r.id: r for r in rows}

    async def get(self, model, key):
        return self.rows.get(key)


async def test_a_rescheduled_cita_keeps_the_first_uid():
    o = office()
    first = appointment(o.id, status="cancelled")
    second = appointment(o.id, status="cancelled", rescheduled_from=first.id)
    third = appointment(o.id, rescheduled_from=second.id)
    uid, moves = await chain_root(ChainDB([first, second, third]), third)
    assert (uid, moves) == (first.id, 2)


async def test_chain_root_stops_at_another_office():
    o = office()
    foreign = appointment(uuid.uuid4())
    mine = appointment(o.id, rescheduled_from=foreign.id)
    assert await chain_root(ChainDB([foreign, mine]), mine) == (mine.id, 0)


# ---------------------------------------------------------------- the endpoint


@pytest.fixture
def endpoint(monkeypatch):
    o = office()
    rows = {}

    class DB:
        async def get(self, model, key):
            return rows.get(key)

    live = {}

    async def resolve(db, appt):
        return live.get(appt.id, appt)

    monkeypatch.setattr(calendar_router, "resolve_active_appointment", resolve)
    return o, rows, live, DB()


async def test_endpoint_serves_the_ics(endpoint):
    o, rows, _, db = endpoint
    a = appointment(o.id)
    rows.update({a.id: a, o.id: o})
    sig = sign_link_value(CALENDAR_LINK_PURPOSE, str(a.id))
    response = await calendar_router.appointment_calendar_file(a.id, sig, db)
    assert response.media_type.startswith("text/calendar")
    assert b"BEGIN:VCALENDAR" in response.body
    assert response.headers["cache-control"] == "no-store"


async def test_endpoint_rejects_a_forged_signature(endpoint):
    o, rows, _, db = endpoint
    a = appointment(o.id)
    rows.update({a.id: a, o.id: o})
    with pytest.raises(NotFoundError):
        await calendar_router.appointment_calendar_file(a.id, "forged", db)


async def test_old_link_serves_the_cita_where_it_is_now(endpoint):
    o, rows, live, db = endpoint
    old = appointment(o.id, status="cancelled")
    new = appointment(o.id, rescheduled_from=old.id, start_datetime=START + timedelta(days=1),
                      end_datetime=START + timedelta(days=1, minutes=45))
    rows.update({old.id: old, new.id: new, o.id: o})
    live[old.id] = new
    sig = sign_link_value(CALENDAR_LINK_PURPOSE, str(old.id))
    response = await calendar_router.appointment_calendar_file(old.id, sig, db)
    body = response.body.decode()
    assert "DTSTART:20260925T220000Z" in body
    assert f"UID:{old.id}@hannibal" in body and "SEQUENCE:1" in body


async def test_cancelled_cita_answers_gone(endpoint):
    o, rows, live, db = endpoint
    a = appointment(o.id, status="cancelled")
    rows.update({a.id: a, o.id: o})
    live[a.id] = None
    sig = sign_link_value(CALENDAR_LINK_PURPOSE, str(a.id))
    response = await calendar_router.appointment_calendar_file(a.id, sig, db)
    assert response.status_code == 410


# ---------------------------------------------------------------- the button


class SendDB:
    def __init__(self, appointments):
        self.appointments = appointments
        self.added, self.commits, self.rollbacks = [], 0, 0

    async def execute(self, stmt):
        wanted = stmt.compile().params["id_1"]
        row = self.appointments.get(wanted)
        return SimpleNamespace(scalar_one_or_none=lambda: row)

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        self.rollbacks += 1


class Client:
    def __init__(self, cta_fails=False):
        self.sent, self.cta_fails = [], cta_fails

    async def send_cta_url(self, **kwargs):
        if self.cta_fails:
            raise RuntimeError("unsupported")
        self.sent.append(("cta", kwargs))
        return "wamid.cta"

    async def send_text_message(self, **kwargs):
        self.sent.append(("text", kwargs))
        return "wamid.text"


def manager(client):
    m = ConversationManager.__new__(ConversationManager)
    m.meta_client = client
    return m


@pytest.fixture
def backend_url(monkeypatch):
    monkeypatch.setattr(calendar_file.settings, "backend_url", "https://api.example.com")


async def test_button_goes_out_for_a_booked_cita(backend_url):
    o = office()
    a = appointment(o.id)
    db, client = SendDB({a.id: a}), Client()
    session = SimpleNamespace(claude_history=[])
    await manager(client)._send_calendar_links(
        db, o, session, SimpleNamespace(id=uuid.uuid4()), "5215550000001", [a.id]
    )
    kind, sent = client.sent[0]
    assert kind == "cta" and sent["button_text"] == "Agregar a calendario"
    assert sent["url"] == calendar_link(a.id)
    assert "jueves 24 de septiembre" in sent["body_text"]
    assert db.added[0].extra_metadata == {"source": "calendar_link"}
    assert session.claude_history[-1]["content"] == sent["body_text"]


async def test_plain_link_when_the_button_is_refused(backend_url):
    o = office()
    a = appointment(o.id)
    client = Client(cta_fails=True)
    await manager(client)._send_calendar_links(
        SendDB({a.id: a}), o, SimpleNamespace(claude_history=[]),
        SimpleNamespace(id=uuid.uuid4()), "5215550000001", [a.id],
    )
    kind, sent = client.sent[0]
    assert kind == "text" and calendar_link(a.id) in sent["text"]


async def test_nothing_for_a_booking_that_was_rolled_back(backend_url):
    o = office()
    client = Client()
    await manager(client)._send_calendar_links(
        SendDB({}), o, SimpleNamespace(claude_history=[]),
        SimpleNamespace(id=uuid.uuid4()), "5215550000001", [uuid.uuid4()],
    )
    assert client.sent == []


async def test_nothing_without_a_backend_url(monkeypatch):
    monkeypatch.setattr(calendar_file.settings, "backend_url", "")
    o = office()
    a = appointment(o.id)
    client = Client()
    await manager(client)._send_calendar_links(
        SendDB({a.id: a}), o, SimpleNamespace(claude_history=[]),
        SimpleNamespace(id=uuid.uuid4()), "5215550000001", [a.id],
    )
    assert client.sent == []
