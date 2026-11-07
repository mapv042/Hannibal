"""Moving a cita to a time that overlaps where it is now doesn't clash with itself.

A reschedule books the new time and cancels the old cita in the same
transaction, so the old cita (and its event in Google) can't be what the new
time collides with: 10:00–10:45 → 10:30 is a valid move.
"""

import uuid
from datetime import datetime, time
from types import SimpleNamespace

from app.core.constants import MX_TIMEZONE
from app.modules.google_calendar.service import CalendarEvent
from app.modules.scheduling import availability, booking
from app.modules.scheduling.availability import BUSY_APPOINTMENT, GoogleView

DAY = datetime(2026, 11, 12, tzinfo=MX_TIMEZONE)
SCHEDULE = SimpleNamespace(
    start_time=time(9), end_time=time(18), appointment_duration_min=30, buffer_minutes=0,
)


def at(hour, minute=0):
    return DAY.replace(hour=hour, minute=minute)


class FakeDB:
    def __init__(self, **rows):
        self.rows = rows

    async def get(self, model, key):
        return SimpleNamespace(google_calendar_token=None)

    async def execute(self, stmt):
        rows = self.rows.get(stmt.column_descriptions[0]["entity"].__name__, [])
        return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: rows))


def cita(start, minutes=45, status="scheduled", google_event_id=None):
    return SimpleNamespace(
        id=uuid.uuid4(), start_datetime=start, end_datetime=None, duration_minutes=minutes,
        status=status, google_event_id=google_event_id,
    )


def no_google(monkeypatch, own=()):
    async def read(*a, **k):
        return GoogleView("ok", [], list(own))

    monkeypatch.setattr(availability, "read_google_calendar", read)


async def test_the_moving_cita_does_not_block_its_new_time(monkeypatch):
    no_google(monkeypatch)
    moving = cita(at(10))
    db = FakeDB(AvailabilitySchedule=[SCHEDULE], Appointment=[moving])

    clash = await availability.check_slot_bookable(uuid.uuid4(), at(10, 30), at(11, 15), db)
    move = await availability.check_slot_bookable(
        uuid.uuid4(), at(10, 30), at(11, 15), db, ignore_appointment_id=moving.id,
    )

    assert clash.kind == BUSY_APPOINTMENT  # anyone else still can't take it
    assert move is None


async def test_another_cita_still_blocks_the_move(monkeypatch):
    no_google(monkeypatch)
    moving, other = cita(at(10)), cita(at(11))
    db = FakeDB(AvailabilitySchedule=[SCHEDULE], Appointment=[moving, other])

    conflict = await availability.check_slot_bookable(
        uuid.uuid4(), at(10, 30), at(11, 15), db, ignore_appointment_id=moving.id,
    )
    assert conflict.kind == BUSY_APPOINTMENT


async def test_the_moving_citas_google_event_is_left_out_too():
    moving = cita(at(10), google_event_id="evt-moving")
    other = cita(at(12))
    db = FakeDB(Appointment=[moving, other], GoogleCalendarEvent=[])
    events = [
        CalendarEvent("evt-moving", "Cita: Ana", at(10), at(10, 45), False),
        CalendarEvent(other.id.hex, "Cita: Luis", at(12), at(12, 45), False),
    ]

    external, own_active = await availability._classify_events(
        uuid.uuid4(), events, db, ignore_appointment_id=moving.id,
    )
    assert external == [] and [e.id for e in own_active] == [other.id.hex]


async def test_nearby_slots_are_offered_for_the_move(monkeypatch):
    no_google(monkeypatch)
    monkeypatch.setattr(availability, "now_mx", lambda: at(0))
    moving = cita(at(10))
    db = FakeDB(AvailabilitySchedule=[SCHEDULE], Appointment=[moving])

    for_anyone = await availability.compute_day_availability(uuid.uuid4(), DAY.date(), db)
    for_the_move = await availability.compute_day_availability(
        uuid.uuid4(), DAY.date(), db, ignore_appointment_id=moving.id,
    )

    assert at(10, 30) not in {s.start_time for s in for_anyone.slots}
    assert at(10, 30) in {s.start_time for s in for_the_move.slots}


async def test_every_reschedule_validates_without_its_old_cita(monkeypatch):
    seen = {}

    async def check(*a, **kw):
        seen.update(kw)
        return None

    monkeypatch.setattr(booking, "check_slot_bookable", check)

    class DB:
        info = {}

        def add(self, obj):
            pass

        async def flush(self):
            pass

    old_id = uuid.uuid4()
    outcome = await booking.book_appointment(
        DB(), SimpleNamespace(id=uuid.uuid4(), google_calendar_token=None),
        patient_id=uuid.uuid4(), start_dt=at(10, 30), duration_min=45, reason="Chequeo",
        appt_type="follow_up", gcal_title="t", gcal_description="d", rescheduled_from=old_id,
    )

    assert outcome.appointment is not None
    assert seen["ignore_appointment_id"] == old_id
