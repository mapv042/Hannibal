"""A cita moved or deleted in the doctor's Google Calendar reaches the system.

Inbound sync used to skip every event Hannibal created: the doctor dragged a
cita to another hour and the patient kept being reminded of the old one. The
change is now applied at once; telling the patient waits for the doctor.
"""

import uuid
from datetime import timedelta
from types import SimpleNamespace

import pytest

from app.db.models import Appointment, Patient
from app.modules.google_calendar import inbound_changes as ic
from app.modules.scheduling.booking import BookingOutcome
from app.utils.dates import now_mx


class FakeDB:
    def __init__(self, patient):
        self.patient = patient

    async def get(self, model, _id):
        return self.patient if model is Patient else None


@pytest.fixture
def calls(monkeypatch):
    recorded = {"book": [], "audit": [], "released": []}

    async def fake_book(db, office, **kwargs):
        recorded["book"].append(kwargs)
        if recorded.get("reject"):
            return BookingOutcome(error="Ese horario está bloqueado.", conflict=True)
        return BookingOutcome(
            appointment=Appointment(
                id=uuid.uuid4(),
                patient_id=kwargs["patient_id"],
                start_datetime=kwargs["start_dt"],
                status="scheduled",
            )
        )

    async def fake_release(office_id, start, redis_client):
        recorded["released"].append(start)

    monkeypatch.setattr(ic, "book_appointment", fake_book)
    monkeypatch.setattr(ic, "release_slot_lock", fake_release)
    monkeypatch.setattr(
        ic, "enqueue_write_audit", lambda appt_id, action, **kw: recorded["audit"].append(action)
    )
    return recorded


def _setup(status="confirmed"):
    start = (now_mx() + timedelta(days=2)).replace(hour=10, minute=0, second=0, microsecond=0)
    patient = Patient(id=uuid.uuid4(), name="María García", phone="5215512345678", whatsapp_id="5215512345678")
    appointment = Appointment(
        id=uuid.uuid4(),
        office_id=uuid.uuid4(),
        patient_id=patient.id,
        start_datetime=start,
        end_datetime=start + timedelta(minutes=30),
        duration_minutes=30,
        status=status,
        google_event_id="evt1",
        consultation_reason="Revisión",
    )
    office = SimpleNamespace(id=appointment.office_id)
    return FakeDB(patient), office, appointment


def _event(start, minutes=30, **extra):
    return {
        "id": "evt1",
        "status": "confirmed",
        "start": {"dateTime": start.isoformat()},
        "end": {"dateTime": (start + timedelta(minutes=minutes)).isoformat()},
        **extra,
    }


async def test_same_time_is_an_echo(calls):
    db, office, appt = _setup()
    assert await ic.apply_calendar_change(db, office, appt, _event(appt.start_datetime), None) is None
    assert calls["book"] == []


async def test_transparent_event_is_our_own_cancellation_echo(calls):
    db, office, appt = _setup()
    event = _event(appt.start_datetime + timedelta(hours=1), transparency="transparent")
    assert await ic.apply_calendar_change(db, office, appt, event, None) is None
    assert appt.status == "confirmed"


async def test_inactive_cita_is_left_alone(calls):
    db, office, appt = _setup(status="cancelled")
    event = _event(appt.start_datetime + timedelta(hours=1))
    assert await ic.apply_calendar_change(db, office, appt, event, None) is None


async def test_deleted_event_cancels_the_cita(calls):
    db, office, appt = _setup()
    notice = await ic.apply_calendar_change(db, office, appt, {"id": "evt1", "status": "cancelled"}, None)
    assert notice["kind"] == ic.CANCELLED
    assert appt.status == "cancelled" and appt.cancelled_by == "doctor"
    assert appt.google_event_id is None
    assert calls["audit"] == ["cancel"]
    assert calls["released"] == [appt.start_datetime]


async def test_moved_event_reschedules_adopting_the_event(calls):
    db, office, appt = _setup()
    new_start = appt.start_datetime + timedelta(hours=3)
    notice = await ic.apply_calendar_change(db, office, appt, _event(new_start, minutes=45), None)

    assert notice["kind"] == ic.MOVED
    booked = calls["book"][0]
    assert booked["existing_google_event_id"] == "evt1"
    assert booked["rescheduled_from"] == appt.id
    assert booked["start_dt"] == new_start
    assert booked["duration_min"] == 45
    assert booked["allow_conflict"] is True
    # The old row gives up the event, or the audit would "repair" it as cancelled.
    assert appt.status == "cancelled" and appt.google_event_id is None
    assert sorted(calls["audit"]) == ["cancel", "reschedule"]
    assert notice["appointment_id"] != str(appt.id)


async def test_move_the_system_refuses_is_reported_not_applied(calls):
    calls["reject"] = True
    db, office, appt = _setup()
    notice = await ic.apply_calendar_change(
        db, office, appt, _event(appt.start_datetime + timedelta(hours=3)), None
    )
    assert notice["kind"] == "rejected"
    assert appt.status == "confirmed" and appt.google_event_id == "evt1"
    assert calls["audit"] == []


async def test_move_into_the_past_is_ignored(calls):
    db, office, appt = _setup()
    past = now_mx() - timedelta(hours=2)
    assert await ic.apply_calendar_change(db, office, appt, _event(past), None) is None
    assert calls["book"] == []


def test_describe_reads_as_one_line():
    moved = {"kind": ic.MOVED, "old_label": "lunes 5 a las 10:00 AM", "new_label": "martes 6 a las 1:00 PM"}
    assert ic.describe(moved) == "la moviste del lunes 5 a las 10:00 AM al martes 6 a las 1:00 PM"
