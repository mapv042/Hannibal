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
from app.modules.google_calendar import outbox
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


# ---------------------------------------------------------------- booking defers


class BookingDB:
    def __init__(self):
        self.info = {}

    def add(self, obj):
        self.row = obj

    async def flush(self):
        pass


async def test_booking_does_not_touch_google_before_the_commit(monkeypatch):
    async def bookable(*a):
        return None

    async def no_google(**kw):
        raise AssertionError("Google was called inside the transaction")

    monkeypatch.setattr(booking, "check_slot_bookable", bookable)
    monkeypatch.setattr(gcal, "create_calendar_event", no_google)
    office = SimpleNamespace(id=uuid.uuid4(), google_calendar_token={"x": 1})
    db = BookingDB()

    outcome = await booking.book_appointment(
        db, office, patient_id=uuid.uuid4(), start_dt=START, duration_min=30,
        reason="Chequeo", appt_type="first_visit", gcal_title="Cita: Ana", gcal_description="d",
    )
    row = outcome.appointment
    assert row.google_event_id is None
    assert outbox.has_pending(db)
    assert db.info["gcal_pending"][str(row.id)]["title"] == "Cita: Ana"


async def test_an_adopted_event_is_not_recreated(monkeypatch):
    async def bookable(*a):
        return None

    monkeypatch.setattr(booking, "check_slot_bookable", bookable)
    office = SimpleNamespace(id=uuid.uuid4(), google_calendar_token={"x": 1})
    db = BookingDB()
    outcome = await booking.book_appointment(
        db, office, patient_id=uuid.uuid4(), start_dt=START, duration_min=30,
        reason="Chequeo", appt_type="first_visit", gcal_title="t", gcal_description="d",
        existing_google_event_id="moved-by-doctor",
    )
    assert outcome.appointment.google_event_id == "moved-by-doctor"
    assert not outbox.has_pending(db)


# ---------------------------------------------------------------- after the commit


class CommittedDB:
    """The committed state apply_pending reads back."""

    def __init__(self, rows):
        self.rows = rows
        self.info = {}
        self.commits = self.rollbacks = 0

    async def get(self, model, key):
        return self.rows.get(key)

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        self.rollbacks += 1


@pytest.fixture
def google_calls(monkeypatch):
    calls = SimpleNamespace(created=[], cancelled=[], moved=[], fail=None, auth_reported=[])

    async def create_event(**kw):
        if calls.fail:
            raise calls.fail
        calls.created.append(kw)
        return kw["event_id"]

    async def mark(office_id, google_event_id, db, note=None):
        if calls.fail:
            raise calls.fail
        calls.cancelled.append((google_event_id, note))

    async def update(**kw):
        calls.moved.append(kw)

    monkeypatch.setattr(gcal, "create_calendar_event", create_event)
    monkeypatch.setattr(gcal, "mark_event_cancelled", mark)
    monkeypatch.setattr(gcal, "update_calendar_event", update)
    monkeypatch.setattr(connection, "should_skip_google", lambda office_id: False)
    monkeypatch.setattr(connection, "report_auth_failure", lambda office_id, e: calls.auth_reported.append(office_id))
    return calls


def committed(appt):
    office = SimpleNamespace(id=appt.office_id, google_calendar_token={"x": 1})
    return CommittedDB({appt.id: appt, appt.office_id: office})


async def test_a_rolled_back_booking_leaves_nothing_in_google(google_calls):
    db = CommittedDB({})
    outbox.defer(db, uuid.uuid4(), title="Cita: Ana")
    assert await outbox.apply_pending(db) == 0
    assert google_calls.created == []


async def test_a_committed_booking_gets_its_event_with_its_own_id(google_calls):
    appt = appointment()
    db = committed(appt)
    outbox.defer(db, appt.id, title="Cita: Ana", description="d", color_id="9")
    assert await outbox.apply_pending(db) == 1
    assert google_calls.created[0]["event_id"] == appt.id.hex
    assert appt.google_event_id == appt.id.hex and db.commits == 1
    assert not outbox.has_pending(db)


async def test_a_committed_cancellation_is_marked_with_its_note(google_calls):
    appt = appointment(status="cancelled", google_event_id="ev1")
    db = committed(appt)
    outbox.defer(db, appt.id, note="Cancelada por el paciente")
    await outbox.apply_pending(db)
    assert google_calls.cancelled == [("ev1", "Cancelada por el paciente")]


async def test_a_rolled_back_reschedule_leaves_the_old_event_alone(google_calls):
    # The turn failed: the old cita is still active in the DB, so its event
    # must not show "[CANCELADA]".
    appt = appointment(status="scheduled", google_event_id="ev1")
    db = committed(appt)
    outbox.defer(db, appt.id, note="Movida al jueves")
    await outbox.apply_pending(db)
    assert google_calls.cancelled == [] and google_calls.created == []


async def test_a_dashboard_move_moves_the_event(google_calls):
    appt = appointment(google_event_id="ev1")
    db = committed(appt)
    outbox.defer(db, appt.id, move=True)
    await outbox.apply_pending(db)
    assert google_calls.moved[0]["google_event_id"] == "ev1"


async def test_rejected_credentials_mark_the_calendar_disconnected(google_calls):
    google_calls.fail = gcal.GoogleCalendarAuthError("revoked")
    appt = appointment(status="cancelled", google_event_id="ev1")
    db = committed(appt)
    outbox.defer(db, appt.id, note="x")
    assert await outbox.apply_pending(db) == 0  # never raises
    assert google_calls.auth_reported == [appt.office_id] and db.rollbacks == 1


async def test_while_disconnected_google_is_not_asked(google_calls, monkeypatch):
    monkeypatch.setattr(connection, "should_skip_google", lambda office_id: True)
    appt = appointment()
    db = committed(appt)
    outbox.defer(db, appt.id, title="Cita")
    await outbox.apply_pending(db)
    assert google_calls.created == []


async def test_one_failure_does_not_stop_the_rest(google_calls):
    a, b = appointment(), appointment()
    db = CommittedDB({
        a.id: a, b.id: b,
        a.office_id: SimpleNamespace(id=a.office_id, google_calendar_token={"x": 1}),
        b.office_id: SimpleNamespace(id=b.office_id, google_calendar_token={"x": 1}),
    })
    outbox.defer(db, a.id, title="A")
    outbox.defer(db, b.id, title="B")
    google_calls.fail = gcal.GoogleCalendarError("down")
    await outbox.apply_pending(db)
    assert db.rollbacks == 2  # both failed, both logged, nothing raised


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


# ---------------------------------------------------------------- cancelling: credentials


@pytest.fixture
def google_events(monkeypatch):
    """A fake Google for GET/PATCH of one event: `script` answers each request in order."""
    state = SimpleNamespace(script=[], requests=[], refreshed=0)

    def handler(request):
        state.requests.append(request.method)
        status = state.script.pop(0)
        return httpx.Response(status, json={"summary": "Cita: Ana"} if status == 200 else {})

    real_client = httpx.AsyncClient

    def client(*args, **kwargs):
        kwargs.pop("timeout", None)
        return real_client(transport=httpx.MockTransport(handler))

    async def token(*a, force_refresh=False, **k):
        state.refreshed += force_refresh
        return "tok"

    monkeypatch.setattr(gcal.httpx, "AsyncClient", client)
    monkeypatch.setattr(gcal, "get_valid_google_token", token)
    monkeypatch.setattr("asyncio.sleep", _no_sleep)
    return state


async def test_rejected_credentials_are_not_mistaken_for_a_missing_event(google_events):
    google_events.script = [403]
    with pytest.raises(gcal.GoogleCalendarAuthError):
        await gcal.mark_event_cancelled("o1", "ev1", OfficeDB())


async def test_an_expired_token_is_refreshed_once(google_events):
    google_events.script = [401, 200, 200]
    await gcal.mark_event_cancelled("o1", "ev1", OfficeDB())
    assert google_events.refreshed == 1 and google_events.requests == ["GET", "GET", "PATCH"]


async def test_a_deleted_event_is_nothing_to_cancel(google_events):
    google_events.script = [404]
    await gcal.mark_event_cancelled("o1", "ev1", OfficeDB())
    assert google_events.requests == ["GET"]


async def test_google_down_is_an_error_not_a_success(google_events):
    google_events.script = [503, 503, 503]
    with pytest.raises(gcal.GoogleCalendarError):
        await gcal.mark_event_cancelled("o1", "ev1", OfficeDB())


async def test_cancel_in_calendar_reports_rejected_credentials(monkeypatch):
    from app.modules.google_calendar import sync

    reported = []

    async def mark(**kw):
        raise gcal.GoogleCalendarAuthError("revoked")

    class DB:
        async def execute(self, stmt):
            return SimpleNamespace(scalar_one_or_none=lambda: SimpleNamespace(google_event_id="ev1"))

    monkeypatch.setattr(sync, "mark_event_cancelled", mark)
    monkeypatch.setattr(connection, "report_auth_failure", lambda office_id, e: reported.append(office_id))
    await sync.cancel_appointment_in_calendar(uuid.uuid4(), "o1", DB())
    assert reported == ["o1"]


# ---------------------------------------------------------------- the audit, after the commit


@pytest.fixture
def dispatched(monkeypatch):
    from app.modules.audit import tasks as audit_tasks

    sent = []
    monkeypatch.setattr(
        audit_tasks, "enqueue_write_audit",
        lambda appointment_id, action, **kw: sent.append((appointment_id, action, kw)),
    )
    return sent


async def test_audits_wait_for_the_commit(google_calls, dispatched):
    appt = appointment()
    db = committed(appt)
    outbox.defer(db, appt.id, title="Cita")
    outbox.defer_audit(db, appt.id, "book", status="scheduled")
    assert dispatched == []  # nothing goes out while the transaction is open
    await outbox.apply_pending(db)
    assert dispatched == [(appt.id, "book", {"status": "scheduled"})]
    assert not outbox.has_pending(db)


class SavepointDB:
    def __init__(self):
        self.info = {}

    def begin_nested(self):
        db = self

        class Savepoint:
            async def __aenter__(self):
                return db

            async def __aexit__(self, *exc):
                return False

        return Savepoint()


@pytest.mark.parametrize("module_name, executor", [
    ("app.modules.ai.tools", "execute_tool"),
    ("app.modules.ai.doctor_tools", "execute_doctor_tool"),
])
async def test_a_tool_that_fails_takes_its_queue_with_it(monkeypatch, module_name, executor):
    import importlib

    module = importlib.import_module(module_name)
    db = SavepointDB()
    kept = uuid.uuid4()
    outbox.defer_audit(db, kept, "book")  # an earlier tool in the same turn

    async def half_done(args, ctx):
        outbox.defer(ctx.db, uuid.uuid4(), title="Cita")
        outbox.defer_audit(ctx.db, uuid.uuid4(), "reschedule")
        raise RuntimeError("boom after the writes")

    monkeypatch.setitem(module._HANDLERS, "half_done", half_done)
    result = await getattr(module, executor)("half_done", {}, SimpleNamespace(db=db))
    assert "error" in result
    assert db.info["gcal_pending"] == {}
    assert [a for a, _, _ in db.info["audit_pending"]] == [kept]
