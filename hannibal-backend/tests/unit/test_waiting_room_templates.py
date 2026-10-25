"""Waiting-room and after-visit messages from the ARGOS test round (P32, P33, P40, P47).

- P32: the doctor hears when the check-in goes unanswered (10 min later).
- P33: after the visit the patient is invited to book the next cita, 10 min
  after the cita ENDS, instead of the old "¿cómo te has sentido?" 2h after start.
- P40: "no voy a llegar" after the check-in reaches the doctor as a last-minute
  cancellation.
- P47: "voy en camino" has its own template, so it reaches a doctor whose
  window is closed.
"""

import uuid
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from app.core.constants import MX_TIMEZONE
from app.modules.notifications import service
from app.modules.reminders import wa_templates as wt
from app.modules.reminders.scheduler import (
    arrival_no_response_due,
    arrival_no_response_still_useful,
    due_at,
    is_still_worth_sending,
)
from app.modules.reminders.tasks import arrival_no_response_due_for
from app.modules.reminders.templates import post_visit_prompt

START = datetime(2026, 10, 14, 10, 0, tzinfo=MX_TIMEZONE)
RULES = [("at_time", 0), ("post_appointment", 10)]


# --------------------------------------------------------------------------- #
# Timing
# --------------------------------------------------------------------------- #

def test_post_visit_message_counts_from_the_end_of_the_cita():
    assert due_at("post_appointment", 10, START, duration_minutes=60) == START + timedelta(minutes=70)
    assert due_at("post_appointment", 10, START, duration_minutes=None) == START + timedelta(minutes=40)
    # Reminders before the cita still count from its start.
    assert due_at("doctor_brief", -15, START, duration_minutes=60) == START - timedelta(minutes=15)


def test_post_visit_grace_also_counts_from_the_end():
    late = START + timedelta(minutes=60 + 10 + 5 * 60)
    assert is_still_worth_sending("post_appointment", 10, START, late, duration_minutes=60)


def test_no_response_is_due_ten_minutes_after_the_check_in():
    due = arrival_no_response_due(0, START)
    assert due == START + timedelta(minutes=10)
    assert arrival_no_response_still_useful(due, due + timedelta(minutes=59))
    assert not arrival_no_response_still_useful(due, due + timedelta(minutes=61))


def _appointment(**overrides):
    fields = dict(
        status="scheduled",
        start_datetime=START,
        arrival_check_sent=True,
        arrival_status=None,
        arrival_no_response_sent=False,
    )
    fields.update(overrides)
    return SimpleNamespace(**fields)


def test_no_response_only_for_an_unanswered_check_in():
    assert arrival_no_response_due_for(_appointment(), RULES) == START + timedelta(minutes=10)
    for overrides in (
        {"arrival_check_sent": False},
        {"arrival_status": "on_the_way"},  # "voy en camino" is an answer
        {"arrival_no_response_sent": True},
        {"status": "cancelled"},
    ):
        assert arrival_no_response_due_for(_appointment(**overrides), RULES) is None
    # An office without the check-in has nothing to report.
    assert arrival_no_response_due_for(_appointment(), [("post_appointment", 10)]) is None


# --------------------------------------------------------------------------- #
# Doctor alerts
# --------------------------------------------------------------------------- #

class _DB:
    def __init__(self, appointment, office, patient):
        self.rows = {appointment.id: appointment, office.id: office, patient.id: patient}

    async def get(self, model, key):
        return self.rows.get(key)

    async def execute(self, stmt):  # the brief's "last visit" lookup
        return SimpleNamespace(scalars=lambda: SimpleNamespace(first=lambda: None))


@pytest.fixture
def alerts(monkeypatch):
    sent = []

    async def fake_alert(redis_client, meta_client, office, **kwargs):
        sent.append(kwargs)
        return "notified"

    monkeypatch.setattr(service, "send_doctor_alert", fake_alert)
    return sent


def _rows(**appointment_fields):
    office = SimpleNamespace(
        id=uuid.uuid4(), notify_cancellation=True, notify_arrival=True, assistant_tone="informal"
    )
    patient = SimpleNamespace(id=uuid.uuid4(), name="Ana Prueba", internal_notes=None)
    fields = dict(
        id=uuid.uuid4(),
        office_id=office.id,
        patient_id=patient.id,
        start_datetime=START,
        arrival_check_sent=False,
        arrival_status=None,
        arrival_eta_minutes=None,
        consultation_reason=None,
        intake_notes=None,
    )
    fields.update(appointment_fields)
    appointment = SimpleNamespace(**fields)
    return appointment, _DB(appointment, office, patient), office


async def test_cancellation_after_check_in_is_a_last_minute_one(alerts):
    appointment, db, _ = _rows(arrival_check_sent=True)

    await service.notify_cancellation(db, None, None, appointment.id)

    assert alerts[0]["template_name"] == wt.TEMPLATE_DOCTOR_PATIENT_NOSHOW_CANCEL
    assert "no llegará" in alerts[0]["text"]


async def test_routine_cancellation_keeps_its_template(alerts):
    appointment, db, _ = _rows(arrival_check_sent=False)

    await service.notify_cancellation(db, None, None, appointment.id)

    assert alerts[0]["template_name"] == wt.TEMPLATE_DOCTOR_CANCELLATION


async def test_on_the_way_uses_the_delayed_template(alerts):
    appointment, db, _ = _rows(arrival_status="on_the_way", arrival_eta_minutes=15)

    await service.notify_arrival(db, None, None, appointment.id)

    assert alerts[0]["template_name"] == wt.TEMPLATE_DOCTOR_PATIENT_DELAYED
    detail = {p["parameter_name"]: p["text"] for p in alerts[0]["template_params"]}["detail"]
    assert detail == "llega en unos 15 minutos a su cita de las 10:00 AM"


async def test_no_response_alert_and_its_toggle(alerts):
    appointment, db, office = _rows(arrival_check_sent=True)

    assert await service.notify_arrival_no_response(db, None, None, appointment.id) == "notified"
    assert alerts[0]["template_name"] == wt.TEMPLATE_DOCTOR_PATIENT_NO_RESPONSE
    assert "no ha respondido" in alerts[0]["text"]

    office.notify_arrival = False
    assert await service.notify_arrival_no_response(db, None, None, appointment.id) == "disabled"
    assert len(alerts) == 1


# --------------------------------------------------------------------------- #
# After-visit message
# --------------------------------------------------------------------------- #

def test_post_visit_message_invites_to_book_in_both_tones():
    data = {"patient_name": "Ana", "office_name": "Consultorio Ruiz"}
    assert post_visit_prompt(data, tone="informal").endswith("¿Quieres agendar tu próxima cita?")
    formal = post_visit_prompt(data, instructions="Tomar ibuprofeno", tone="formal")
    assert "Indicaciones:\nTomar ibuprofeno" in formal
    assert formal.endswith("¿Desea agendar su próxima cita?")


def test_follow_up_is_the_booking_invitation_with_buttons():
    (follow_up,) = [s for s in wt.TEMPLATE_SPECS if s.name == wt.TEMPLATE_FOLLOW_UP]
    assert "¿Quieres agendar tu próxima cita?" in follow_up.body
    assert follow_up.quick_replies == ("Agendar cita", "Ahora no")
