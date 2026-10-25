"""The patient hears "le avisé al doctor" only if the alert went out (ARGOS P47, P48)."""

import uuid
from types import SimpleNamespace

import pytest

from app.modules.ai import tools
from app.modules.ai.tools import TOOL_CLAIMS
from app.modules.conversation.base_manager import _claims_backed
from app.modules.conversation.state import ConversationState
from app.modules.notifications import service as notifications
from app.modules.whatsapp import transport


@pytest.fixture
def arrival(monkeypatch):
    office = SimpleNamespace(id=uuid.uuid4(), name="Consultorio")
    appointment = SimpleNamespace(
        id=uuid.uuid4(),
        arrival_status=None,
        arrival_reported_at=None,
        arrival_eta_minutes=None,
    )

    async def load(appt_id, ctx):
        return appointment, None

    monkeypatch.setattr(tools, "_load_actionable_appointment", load)
    monkeypatch.setattr(transport, "get_meta_client", lambda: object())
    ctx = SimpleNamespace(office=office, db=object(), redis_client=object(), state=ConversationState())
    return ctx, appointment


def _alert_returns(monkeypatch, outcome, seen=None):
    async def fake_notify(db, redis_client, meta_client, appointment_id):
        if seen is not None:
            seen.append(appointment_id)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(notifications, "notify_arrival", fake_notify)


async def test_alert_sent_backs_the_claim(arrival, monkeypatch):
    ctx, appointment = arrival
    seen = []
    _alert_returns(monkeypatch, "notified", seen)

    result = await tools._handle_report_arrival(
        {"appointment_id": str(appointment.id), "status": "arrived"}, ctx
    )

    assert seen == [appointment.id]
    assert result["doctor_notified"] is True
    assert "Se avisó al doctor" in result["summary"]
    assert _claims_backed("report_arrival", result, TOOL_CLAIMS) == {"notify_doctor"}


@pytest.mark.parametrize("outcome", ["skipped", RuntimeError("Meta 500")])
async def test_alert_not_sent_withholds_the_claim(arrival, monkeypatch, outcome):
    ctx, appointment = arrival
    _alert_returns(monkeypatch, outcome)

    result = await tools._handle_report_arrival(
        {"appointment_id": str(appointment.id), "status": "on_the_way", "eta_minutes": 15},
        ctx,
    )

    assert appointment.arrival_status == "on_the_way"  # still recorded for the waiting room
    assert result["doctor_notified"] is False
    assert "No le digas que le avisaste" in result["next_step"]
    assert _claims_backed("report_arrival", result, TOOL_CLAIMS) == frozenset()
