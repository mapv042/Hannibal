"""A cita's Google event: retried, never duplicated, and repaired by the audit."""

import json
import uuid
from datetime import datetime, timedelta
from types import SimpleNamespace

import httpx
import pytest

from app.core.constants import MX_TIMEZONE
from app.modules.audit import service as audit
from app.modules.google_calendar import connection
from app.modules.google_calendar import service as gcal
from app.modules.scheduling import booking

START = datetime(2026, 9, 30, 9, tzinfo=MX_TIMEZONE)


async def _no_sleep(*a, **k):
    return None


class OfficeDB:
    """Just enough of a session for create_calendar_event (it loads the office)."""

    def __init__(self):
        self.office = SimpleNamespace(google_calendar_id="primary")

    async def get(self, model, key):
        return self.office


@pytest.fixture
def google(monkeypatch):
    """A fake Google: `script` lists what each POST answers (status or exception)."""
    state = SimpleNamespace(script=[], bodies=[])

    def handler(request):
        state.bodies.append(json.loads(request.content))
        step = state.script.pop(0)
        if isinstance(step, Exception):
            raise step
        body = {"id": state.bodies[-1].get("id", "generated-id")} if step in (200, 201) else {}
        return httpx.Response(step, json=body)

    real_client = httpx.AsyncClient

    def client(*args, **kwargs):
        kwargs.pop("timeout", None)
        return real_client(transport=httpx.MockTransport(handler))

    async def token(*a, **k):
        return "tok"

    monkeypatch.setattr(gcal.httpx, "AsyncClient", client)
    monkeypatch.setattr(gcal, "get_valid_google_token", token)
    monkeypatch.setattr("asyncio.sleep", _no_sleep)
    return state


async def create(event_id="abc12345"):
    return await gcal.create_calendar_event(
        office_id="o1", title="Cita: Ana", start_time=START, end_time=START + timedelta(minutes=30),
        description="", db=OfficeDB(), event_id=event_id,
    )


def test_event_id_is_the_appointment_id_in_google_format():
    appointment_id = uuid.UUID("12345678-9abc-def0-1234-56789abcdef0")
    event_id = gcal.calendar_event_id_for(appointment_id)
    assert event_id == "123456789abcdef0123456789abcdef0"
    # Google: lowercase base32hex (0-9, a-v), 5 to 1024 characters.
    assert set(event_id) <= set("0123456789abcdefghijklmnopqrstuv") and 5 <= len(event_id) <= 1024


async def test_the_event_is_created_with_the_chosen_id(google):
    google.script = [200]
    assert await create("abc12345") == "abc12345"
    assert google.bodies[0]["id"] == "abc12345"


async def test_a_google_hiccup_is_retried(google):
    google.script = [503, 500, 200]
    assert await create() == "abc12345"
    assert len(google.bodies) == 3


async def test_a_timeout_that_did_create_the_event_is_not_a_duplicate(google):
    # The first POST created it but the answer never came back; the retry is told
    # it already exists. One event, and the booking keeps its id.
    google.script = [httpx.ReadTimeout("slow"), 409]
    assert await create("abc12345") == "abc12345"
    assert [b["id"] for b in google.bodies] == ["abc12345", "abc12345"]


async def test_a_client_error_is_not_retried(google):
    google.script = [400]
    with pytest.raises(Exception):
        await create()
    assert len(google.bodies) == 1


async def test_without_an_id_a_conflict_is_still_an_error(google):
    google.script = [409]
    with pytest.raises(Exception):
        await create(event_id=None)


async def test_google_down_for_every_attempt_raises(google):
    google.script = [503, 503, 503]
    with pytest.raises(Exception):
        await create()


# ---------------------------------------------------------------- booking


async def test_booking_creates_the_event_with_its_own_id(monkeypatch):
    seen = {}

    async def bookable(*a):
        return None

    async def create_event(**kw):
        seen.update(kw)
        return kw["event_id"]

    class DB:
        def add(self, obj):
            seen["row"] = obj

        async def flush(self):
            pass

    monkeypatch.setattr(booking, "check_slot_bookable", bookable)
    monkeypatch.setattr(booking, "create_calendar_event", create_event)
    monkeypatch.setattr(connection, "should_skip_google", lambda office_id: False)
    office = SimpleNamespace(id=uuid.uuid4(), google_calendar_token={"x": 1})

    outcome = await booking.book_appointment(
        DB(), office, patient_id=uuid.uuid4(), start_dt=START, duration_min=30,
        reason="Chequeo", appt_type="first_visit", gcal_title="Cita", gcal_description="",
    )
    row = outcome.appointment
    assert seen["event_id"] == row.id.hex
    assert row.google_event_id == row.id.hex


async def test_a_failed_event_still_books_the_cita(monkeypatch):
    async def bookable(*a):
        return None

    async def create_event(**kw):
        raise gcal.GoogleCalendarError("google down")

    class DB:
        def add(self, obj):
            pass

        async def flush(self):
            pass

    monkeypatch.setattr(booking, "check_slot_bookable", bookable)
    monkeypatch.setattr(booking, "create_calendar_event", create_event)
    monkeypatch.setattr(connection, "should_skip_google", lambda office_id: False)
    office = SimpleNamespace(id=uuid.uuid4(), google_calendar_token={"x": 1})

    outcome = await booking.book_appointment(
        DB(), office, patient_id=uuid.uuid4(), start_dt=START, duration_min=30,
        reason="Chequeo", appt_type="first_visit", gcal_title="Cita", gcal_description="",
    )
    assert outcome.appointment is not None and outcome.appointment.google_event_id is None


# ---------------------------------------------------------------- the audit's repair


def appointment(**kw):
    base = dict(
        id=uuid.uuid4(), office_id=uuid.uuid4(), patient_id=uuid.uuid4(), google_event_id=None,
        status="scheduled", type="first_visit", consultation_reason="Chequeo",
        start_datetime=START, end_datetime=START + timedelta(minutes=30),
    )
    base.update(kw)
    return SimpleNamespace(**base)


class AuditDB:
    def __init__(self, patient=None):
        self.patient = patient

    async def get(self, model, key):
        return self.patient

    async def flush(self):
        pass


@pytest.fixture
def audit_world(monkeypatch):
    w = SimpleNamespace(created=[], event={"status": "confirmed"}, fail=False, alerts=[])

    async def create_event(**kw):
        if w.fail:
            raise gcal.GoogleCalendarError("still down")
        w.created.append(kw)
        return kw["event_id"]

    async def get_event(office_id, event_id, db):
        return w.event

    async def alert(*a, **k):
        w.alerts.append(k)

    async def not_alerted(*a):
        return False

    async def connected(*a):
        return False

    monkeypatch.setattr(gcal, "create_calendar_event", create_event)
    monkeypatch.setattr(audit, "get_calendar_event", get_event)
    monkeypatch.setattr(audit, "send_doctor_alert", alert)
    monkeypatch.setattr(audit, "_already_alerted", not_alerted)
    monkeypatch.setattr(connection, "is_disconnected", connected)
    return w


def audit_office():
    return SimpleNamespace(id=uuid.uuid4(), google_calendar_token={"x": 1})


async def run_audit(appt, action="book", patient=None):
    office = audit_office()

    class DB(AuditDB):
        async def get(self, model, key):
            if model is audit.Appointment:
                return appt
            if model is audit.Office:
                return office
            return patient

    return await audit.verify_appointment_write(
        DB(), None, None, appt.id,
        {"action": action, "status": "scheduled", "start_datetime": START.isoformat()},
    )


async def test_the_audit_creates_the_missing_event_instead_of_alerting(audit_world):
    appt = appointment()
    patient = SimpleNamespace(name="Ana López", phone="5215512345678")
    assert await run_audit(appt, patient=patient) == "ok"
    created = audit_world.created[0]
    assert created["event_id"] == appt.id.hex and created["title"] == "Cita: Ana López"
    assert appt.google_event_id == appt.id.hex
    assert audit_world.alerts == []


async def test_an_urgent_cita_is_repaired_as_an_urgency(audit_world):
    appt = appointment(type="urgent")
    await run_audit(appt, patient=SimpleNamespace(name="Ana", phone=None))
    assert audit_world.created[0]["title"] == "URGENCIA: Ana"


async def test_if_the_repair_fails_the_doctor_is_told(audit_world):
    audit_world.fail = True
    appt = appointment()
    assert await run_audit(appt, patient=SimpleNamespace(name="Ana", phone=None)) == "diverged"
    assert len(audit_world.alerts) == 1


async def test_an_event_the_doctor_deleted_is_not_recreated(audit_world):
    # The cita had an event and it's gone: that's the doctor's call (inbound
    # sync cancels it), not something to paper over.
    audit_world.event = None
    appt = appointment(google_event_id="ev-from-before")
    assert await run_audit(appt, patient=SimpleNamespace(name="Ana", phone=None)) == "diverged"
    assert audit_world.created == []


# ---------------------------------------------------------------- backfill


async def test_the_backfill_uses_the_same_idempotent_id(monkeypatch):
    created = []

    async def create_event(**kw):
        created.append(kw)
        return kw["event_id"]

    monkeypatch.setattr(gcal, "create_calendar_event", create_event)
    appt = appointment(status="confirmed")
    await connection.create_appointment_event(None, appt, SimpleNamespace(name=None, phone=None), "nota")
    assert created[0]["event_id"] == appt.id.hex
    assert created[0]["title"] == "Cita: Paciente" and created[0]["color_id"] == "10"
    assert created[0]["description"].endswith("nota")
