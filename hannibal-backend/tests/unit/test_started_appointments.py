"""An appointment whose time is over can't be cancelled or moved (ARGOS P04–P06).

The doctor's day listing used to hand back this morning's visit as a cancel
candidate in the afternoon, and both flows would cancel or "move" it.
"""

import uuid
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from app.core.constants import MX_TIMEZONE
from app.modules.ai import doctor_tools as dt
from app.modules.ai import tool_helpers
from app.modules.ai import tools

NOW = datetime(2026, 10, 12, 12, 20, tzinfo=MX_TIMEZONE)


@pytest.fixture(autouse=True)
def frozen_clock(monkeypatch):
    monkeypatch.setattr(tool_helpers, "now_mx", lambda: NOW)


def _appointment(office_id, start, status="scheduled"):
    return SimpleNamespace(
        id=uuid.uuid4(),
        office_id=office_id,
        patient_id=uuid.uuid4(),
        start_datetime=start,
        duration_minutes=30,
        status=status,
        consultation_reason="Revisión",
        post_consultation_notes=None,
    )


def test_ended_appointment_error_only_once_the_cita_is_over():
    office_id = uuid.uuid4()
    past = _appointment(office_id, NOW.replace(hour=9, minute=40))
    under_way = _appointment(office_id, NOW.replace(hour=12, minute=0))
    future = _appointment(office_id, NOW.replace(hour=18))

    assert "ya concluyó" in tool_helpers.ended_appointment_error(past)
    # P40: at the check-in "no voy a llegar" must still be able to cancel it.
    assert tool_helpers.ended_appointment_error(under_way) is None
    assert tool_helpers.ended_appointment_error(future) is None


async def test_patient_cannot_cancel_an_appointment_that_already_happened(monkeypatch):
    office = SimpleNamespace(id=uuid.uuid4())
    past = _appointment(office.id, NOW.replace(hour=9))

    async def load(appt_id, ctx):
        return past, None

    monkeypatch.setattr(tools, "_load_actionable_appointment", load)
    ctx = SimpleNamespace(office=office)

    result = await tools._handle_cancel_appointment({"appointment_id": str(past.id)}, ctx)

    assert "ya concluyó" in result["error"]
    assert past.status == "scheduled"


async def test_patient_cannot_move_an_appointment_that_already_happened(monkeypatch):
    office = SimpleNamespace(id=uuid.uuid4())
    past = _appointment(office.id, NOW.replace(hour=9))

    async def load(appt_id, ctx):
        return past, None

    async def no_gate(ctx, tool_name):
        return None

    monkeypatch.setattr(tools, "_load_actionable_appointment", load)
    monkeypatch.setattr(tools, "_privacy_gate", no_gate)
    monkeypatch.setattr(tools, "now_mx", lambda: NOW)
    ctx = SimpleNamespace(office=office)

    result = await tools._handle_prepare_booking(
        {
            "slot_id": "2026-10-12T17:00",
            "for_self": True,
            "replaces_appointment_id": str(past.id),
        },
        ctx,
    )

    assert "ya concluyó" in result["error"]


class _DoctorDB:
    def __init__(self, appointments, patient=None):
        self.appointments = {a.id: a for a in appointments}
        self.patient = patient

    async def get(self, model, key):
        return self.appointments.get(key) or self.patient

    async def execute(self, stmt):
        rows = list(self.appointments.values())
        return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: rows))


@pytest.mark.parametrize("handler,args", [
    (dt._handle_cancel_appointment, {}),
    (dt._handle_reschedule_appointment, {"new_date": "2026-10-15", "new_time": "17:00"}),
])
async def test_doctor_cannot_cancel_or_move_a_past_appointment(handler, args):
    office = SimpleNamespace(id=uuid.uuid4(), google_calendar_token=None)
    past = _appointment(office.id, NOW.replace(hour=9, minute=40))
    ctx = SimpleNamespace(office=office, db=_DoctorDB([past]))

    result = await handler({"appointment_id": str(past.id), **args}, ctx)

    assert "ya concluyó" in result["error"]
    assert "mark_appointment_status" in result["next_step"]
    assert past.status == "scheduled"


async def test_doctor_listing_flags_appointments_that_already_happened(monkeypatch):
    monkeypatch.setattr(dt, "now_mx", lambda: NOW)
    office = SimpleNamespace(id=uuid.uuid4())
    morning = _appointment(office.id, NOW.replace(hour=9, minute=40))
    evening = _appointment(office.id, NOW.replace(hour=18))
    patient = SimpleNamespace(name="Ana Prueba")
    ctx = SimpleNamespace(office=office, db=_DoctorDB([morning, evening], patient))

    result = await dt._handle_get_appointments({}, ctx)

    flags = {e["id"]: e.get("already_happened", False) for e in result["appointments"]}
    assert flags == {str(morning.id): True, str(evening.id): False}
    assert "mark_appointment_status" in result["note"]


def test_patient_cancellation_does_not_require_a_reason():
    """ARGOS P09: a patient who won't say why still gets to cancel."""
    (cancel,) = [t for t in tools.TOOL_DEFINITIONS if t["name"] == "cancel_appointment"]
    assert cancel["input_schema"]["required"] == ["appointment_id"]
