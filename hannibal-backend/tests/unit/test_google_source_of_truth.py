"""Google Calendar is the source of truth for the doctor's time.

An event the doctor put in Google occupies that hour for every flow: the
patient's slots, the doctor's bookings (no overbook over it) and the doctor's
"¿tengo algo agendado?". Our own citas' events are told apart by id, so they
stay overbookable like the cita itself.
"""

import uuid
from datetime import datetime, time, timedelta
from types import SimpleNamespace

import httpx
import pytest

from app.core.constants import MX_TIMEZONE
from app.core.exceptions import GoogleCalendarAuthError, GoogleCalendarError
from app.db.models import TimeBlock
from app.modules.ai import doctor_tools as dt
from app.modules.google_calendar import service as gcal
from app.modules.google_calendar.service import CalendarEvent
from app.modules.scheduling import availability, booking
from app.modules.scheduling.availability import (
    BUSY_APPOINTMENT,
    BUSY_GOOGLE,
    BUSY_TIME_BLOCK,
    GoogleView,
    SlotConflict,
)

DAY = datetime(2026, 11, 12, tzinfo=MX_TIMEZONE)  # a Thursday


def at(hour, minute=0):
    return DAY.replace(hour=hour, minute=minute)


def event(event_id, start, end, summary="Junta", all_day=False):
    return CalendarEvent(id=event_id, summary=summary, start=start, end=end, all_day=all_day)


class FakeDB:
    """Answers each query by the entity it selects; records the statements."""

    def __init__(self, office=None, **rows):
        self.office = office or SimpleNamespace(google_calendar_token={"x": 1}, google_calendar_id=None)
        self.rows = rows
        self.statements = []

    async def get(self, model, key):
        return self.office

    async def execute(self, stmt):
        self.statements.append(stmt)
        entity = stmt.column_descriptions[0]["entity"]
        rows = self.rows.get(entity.__name__, [])
        return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: rows))

    def sql_for(self, entity):
        return [str(s) for s in self.statements if s.column_descriptions[0]["entity"] is entity]


SCHEDULE = SimpleNamespace(
    start_time=time(9), end_time=time(18), appointment_duration_min=30, buffer_minutes=0,
)


def google_says(monkeypatch, status="ok", external=(), own=()):
    async def read(*a, **k):
        return GoogleView(status, list(external), list(own))

    monkeypatch.setattr(availability, "read_google_calendar", read)


# ------------------------------------------------------------- reading Google


@pytest.fixture
def google_api(monkeypatch):
    state = SimpleNamespace(responses=[], requests=[])

    def handler(request):
        state.requests.append(request)
        status, body = state.responses.pop(0)
        return httpx.Response(status, json=body)

    real = httpx.AsyncClient

    def client(*a, **kw):
        kw.pop("timeout", None)
        return real(transport=httpx.MockTransport(handler))

    async def token(*a, **k):
        return "tok"

    monkeypatch.setattr(gcal.httpx, "AsyncClient", client)
    monkeypatch.setattr(gcal, "get_valid_google_token", token)
    return state


def _g(event_id, start, end, **extra):
    return {
        "id": event_id, "summary": event_id,
        "start": {"dateTime": start.isoformat()}, "end": {"dateTime": end.isoformat()},
        **extra,
    }


async def test_only_events_that_occupy_time_are_busy(google_api):
    google_api.responses = [(200, {"items": [
        _g("busy", at(10), at(11)),
        _g("free", at(11), at(12), transparency="transparent"),
        _g("gone", at(12), at(13), status="cancelled"),
        _g("declined", at(13), at(14), attendees=[{"self": True, "responseStatus": "declined"}]),
        _g("where", at(9), at(18), eventType="workingLocation"),
        {"id": "allday", "summary": "Congreso",
         "start": {"date": "2026-11-12"}, "end": {"date": "2026-11-13"}},
    ]})]

    events = await gcal.list_busy_events("o1", at(0), at(23, 59), FakeDB())

    assert [e.id for e in events] == ["busy", "allday"]
    allday = events[1]
    assert allday.all_day and allday.start == at(0) and allday.end == at(0) + timedelta(days=1)


async def test_pages_are_followed(google_api):
    google_api.responses = [
        (200, {"items": [_g("a", at(10), at(11))], "nextPageToken": "p2"}),
        (200, {"items": [_g("b", at(12), at(13))]}),
    ]
    events = await gcal.list_busy_events("o1", at(0), at(23, 59), FakeDB())
    assert [e.id for e in events] == ["a", "b"]
    assert google_api.requests[1].url.params["pageToken"] == "p2"


async def test_rejected_credentials_are_typed(google_api):
    google_api.responses = [(401, {}), (403, {})]  # refreshed once, still refused
    with pytest.raises(GoogleCalendarAuthError):
        await gcal.list_busy_events("o1", at(0), at(23, 59), FakeDB())


async def test_an_outage_is_not_an_empty_calendar(google_api):
    google_api.responses = [(503, {})]
    with pytest.raises(GoogleCalendarError) as exc:
        await gcal.list_busy_events("o1", at(0), at(23, 59), FakeDB())
    assert not isinstance(exc.value, GoogleCalendarAuthError)


# ------------------------------------------------- our citas vs the doctor's own


async def test_our_citas_events_are_told_apart_from_the_doctors_own():
    office_id = uuid.uuid4()
    active = SimpleNamespace(id=uuid.uuid4(), google_event_id=None, status="scheduled")
    cancelled = SimpleNamespace(id=uuid.uuid4(), google_event_id="legacy-id", status="cancelled")
    db = FakeDB(Appointment=[active, cancelled], GoogleCalendarEvent=["block-we-wrote"])
    events = [
        event("personal", at(10), at(11)),
        event(active.id.hex, at(12), at(12, 30)),       # created with calendar_event_id_for
        event("legacy-id", at(13), at(13, 30)),         # a cancelled cita's stale event
        event("block-we-wrote", at(16), at(17)),        # its TimeBlock row already counts
    ]

    external, own_active = await availability._classify_events(office_id, events, db)

    assert [e.id for e in external] == ["personal"]
    assert [e.id for e in own_active] == [active.id.hex]


# ------------------------------------------------------------ booking checks


async def test_a_google_event_blocks_the_slot_and_is_named_for_the_doctor(monkeypatch):
    google_says(monkeypatch, external=[event("e1", at(10), at(11), "Comida con Luis")])
    db = FakeDB(AvailabilitySchedule=[SCHEDULE])

    conflict = await availability.check_slot_bookable(uuid.uuid4(), at(10, 30), at(11), db)

    assert conflict.kind == BUSY_GOOGLE
    assert "Comida con Luis" in conflict.detail and "10:00" in conflict.detail
    assert "Comida" not in conflict.message  # the patient never learns what it is


async def test_google_outranks_another_cita_so_an_overbook_cant_slip_past(monkeypatch):
    google_says(monkeypatch, external=[event("e1", at(10), at(11))])
    cita = SimpleNamespace(
        start_datetime=at(10), end_datetime=at(10, 30), duration_minutes=30,
    )
    db = FakeDB(AvailabilitySchedule=[SCHEDULE], Appointment=[cita])

    conflict = await availability.check_slot_bookable(uuid.uuid4(), at(10), at(10, 30), db)

    assert conflict.kind == BUSY_GOOGLE


async def test_our_own_citas_event_stays_an_overbookable_cita(monkeypatch):
    google_says(monkeypatch, own=[event("ours", at(10), at(10, 30))])
    db = FakeDB(AvailabilitySchedule=[SCHEDULE])

    conflict = await availability.check_slot_bookable(uuid.uuid4(), at(10), at(10, 30), db)

    assert conflict.kind == BUSY_APPOINTMENT


async def test_copies_of_google_events_count_only_when_google_cant_be_read(monkeypatch):
    google_says(monkeypatch, status="ok")
    live = FakeDB(AvailabilitySchedule=[SCHEDULE])
    await availability.check_slot_bookable(uuid.uuid4(), at(10), at(10, 30), live)
    assert "time_blocks.origin !=" in live.sql_for(TimeBlock)[0]

    google_says(monkeypatch, status="disconnected")
    fallback = FakeDB(AvailabilitySchedule=[SCHEDULE])
    await availability.check_slot_bookable(uuid.uuid4(), at(10), at(10, 30), fallback)
    assert "time_blocks.origin !=" not in fallback.sql_for(TimeBlock)[0]


async def test_patient_slots_skip_what_google_has(monkeypatch):
    google_says(monkeypatch, external=[event("e1", at(10), at(11))])
    monkeypatch.setattr(availability, "now_mx", lambda: at(0))
    db = FakeDB(AvailabilitySchedule=[SCHEDULE])

    day = await availability.compute_day_availability(uuid.uuid4(), DAY.date(), db)

    starts = {s.start_time for s in day.slots}
    assert at(10) not in starts and at(10, 30) not in starts
    assert at(9, 30) in starts and at(11) in starts


# ---------------------------------------------------------------- the booking


class BookingDB:
    def __init__(self):
        self.info = {}

    def add(self, obj):
        self.row = obj

    async def flush(self):
        pass


def _conflict(monkeypatch, conflict):
    async def check(*a):
        return conflict

    monkeypatch.setattr(booking, "check_slot_bookable", check)


async def _book(**kw):
    office = SimpleNamespace(id=uuid.uuid4(), google_calendar_token=None)
    return await booking.book_appointment(
        BookingDB(), office, patient_id=uuid.uuid4(), start_dt=at(10), duration_min=30,
        reason="Chequeo", appt_type="first_visit", gcal_title="t", gcal_description="d", **kw,
    )


async def test_the_doctor_cannot_overbook_on_top_of_a_google_event(monkeypatch):
    _conflict(monkeypatch, SlotConflict(BUSY_GOOGLE, "ocupado", "«Junta» de 10:00 AM a 11:00 AM"))

    outcome = await _book(allow_conflict=True)

    assert outcome.appointment is None and outcome.conflict_kind == BUSY_GOOGLE
    assert outcome.conflict_detail == "«Junta» de 10:00 AM a 11:00 AM"


async def test_the_doctor_can_still_overbook_another_cita(monkeypatch):
    _conflict(monkeypatch, SlotConflict(BUSY_APPOINTMENT, "ocupado"))
    assert (await _book(allow_conflict=True)).appointment is not None


async def test_a_cita_the_doctor_dragged_in_google_lands_where_they_put_it(monkeypatch):
    _conflict(monkeypatch, SlotConflict(BUSY_GOOGLE, "ocupado", "x"))
    outcome = await _book(allow_conflict=True, existing_google_event_id="dragged")
    assert outcome.appointment is not None


async def test_a_block_stays_hard_even_for_a_dragged_cita(monkeypatch):
    _conflict(monkeypatch, SlotConflict(BUSY_TIME_BLOCK, "bloqueado"))
    outcome = await _book(allow_conflict=True, existing_google_event_id="dragged")
    assert outcome.appointment is None


def test_the_doctor_is_told_what_the_slot_collides_with_and_not_offered_an_overbook():
    outcome = booking.BookingOutcome(
        error="Ese horario está ocupado en el calendario del doctor.", conflict=True,
        conflict_kind=BUSY_GOOGLE, conflict_detail="«Junta» de 10:00 AM a 11:00 AM en tu Google Calendar",
    )
    result = dt._doctor_booking_error(outcome)
    assert result["conflicts_with"].startswith("«Junta»")
    assert "allow_conflict=true" not in result["next_step"]
    assert "Google Calendar" in result["next_step"]


# ----------------------------------------------------- "¿tengo algo agendado?"


def _doctor_ctx(monkeypatch, view=None, error=None, blocks=()):
    async def read(*a, **k):
        if error:
            raise error
        return view

    monkeypatch.setattr(dt, "read_google_calendar", read)
    db = FakeDB(TimeBlock=list(blocks))
    return SimpleNamespace(office=SimpleNamespace(id=uuid.uuid4()), db=db)


async def test_the_agenda_shows_what_the_doctor_put_in_google(monkeypatch):
    ctx = _doctor_ctx(monkeypatch, GoogleView(
        "ok", [event("e1", at(13), at(14), "Comida con Luis")], [],
    ))

    result = await dt._handle_get_appointments({"date": "2026-11-12"}, ctx)

    assert result["appointments"] == []
    (shown,) = result["google_calendar_events"]
    assert shown["title"] == "Comida con Luis"
    assert "1:00 PM" in shown["label"] and "2:00 PM" in shown["label"]
    assert "No hay citas de pacientes" in result["message"]
    assert "ocupadas" in result["message"]
    # The live read is the truth: the stale copies of Google events are left out.
    assert "time_blocks.origin !=" in ctx.db.sql_for(TimeBlock)[0]


async def test_an_empty_day_says_so_only_when_google_was_checked(monkeypatch):
    ctx = _doctor_ctx(monkeypatch, GoogleView("ok", [], []))
    result = await dt._handle_get_appointments({"date": "2026-11-12"}, ctx)
    assert "ni eventos en el calendario" in result["message"]

    ctx = _doctor_ctx(monkeypatch, error=GoogleCalendarError("503"))
    result = await dt._handle_get_appointments({"date": "2026-11-12"}, ctx)
    assert "ni eventos" not in result["message"]
    assert "no afirmes que el día está libre" in result["calendar_note"]


async def test_a_blocked_day_is_part_of_the_agenda(monkeypatch):
    vacation = SimpleNamespace(
        start_date=at(0), end_date=at(23, 59), is_all_day=True,
        reason="Vacaciones", origin="manual",
    )
    ctx = _doctor_ctx(monkeypatch, GoogleView("ok", [], []), blocks=[vacation])

    result = await dt._handle_get_appointments({"date": "2026-11-12"}, ctx)

    (block,) = result["blocks"]
    assert block["reason"] == "Vacaciones" and "todo el día" in block["label"]
