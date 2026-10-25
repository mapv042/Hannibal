"""Patient cancellation: one confirmation that asks the reason once (ARGOS P09).

The first cancel_appointment call only asks; the cita is cancelled by a call in
a later turn — with the reason if the patient gave one, without it otherwise.
"""

import uuid
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from app.core.constants import MX_TIMEZONE
from app.modules.ai import tool_helpers, tools
from app.modules.ai.tools import TOOL_CLAIMS
from app.modules.conversation.base_manager import _claims_backed
from app.modules.conversation.state import ConversationState

NOW = datetime(2026, 10, 12, 10, 0, tzinfo=MX_TIMEZONE)


@pytest.fixture
def cancellation(monkeypatch):
    monkeypatch.setattr(tools, "now_mx", lambda: NOW)
    monkeypatch.setattr(tool_helpers, "now_mx", lambda: NOW)
    office = SimpleNamespace(id=uuid.uuid4(), assistant_tone="informal")
    appointment = SimpleNamespace(
        id=uuid.uuid4(),
        office_id=office.id,
        patient_id=uuid.uuid4(),
        start_datetime=NOW.replace(hour=18),
        duration_minutes=30,
        status="scheduled",
        cancelled_by=None,
        cancellation_reason=None,
    )

    async def load(appt_id, ctx):
        return appointment, None

    async def noop(*args, **kwargs):
        return None

    monkeypatch.setattr(tools, "_load_actionable_appointment", load)
    monkeypatch.setattr(tools, "_invalidate_avail", noop)
    monkeypatch.setattr(tools, "_release_slot", noop)
    monkeypatch.setattr(tools, "cancel_appointment_in_calendar", noop)
    monkeypatch.setattr(tools, "find_pending_doctor_cancellation", noop)
    monkeypatch.setattr(tools, "enqueue_cancellation_notification", lambda *a: None)
    monkeypatch.setattr(tools, "enqueue_write_audit", lambda *a, **k: None)
    state = ConversationState()

    def ctx(turn_started_at):
        return SimpleNamespace(
            office=office, db=None, redis_client=None, state=state,
            turn_started_at=turn_started_at,
        )

    return ctx, appointment


async def test_first_call_asks_instead_of_cancelling(cancellation):
    ctx, appointment = cancellation

    result = await tools._handle_cancel_appointment(
        {"appointment_id": str(appointment.id)}, ctx(NOW)
    )

    assert appointment.status == "scheduled"
    assert result["confirmation_needed"] is True
    assert result["reason_given"] is False
    assert "cuál es el motivo" in result["next_step"]
    assert _claims_backed("cancel_appointment", result, TOOL_CLAIMS) == frozenset()


async def test_reason_given_upfront_is_not_asked_and_is_kept(cancellation):
    ctx, appointment = cancellation
    first = await tools._handle_cancel_appointment(
        {"appointment_id": str(appointment.id), "reason": "Me salió trabajo"}, ctx(NOW)
    )
    assert first["reason_given"] is True
    assert "motivo de la cancelación" not in first["next_step"]

    await tools._handle_cancel_appointment(
        {"appointment_id": str(appointment.id)}, ctx(NOW + timedelta(minutes=1))
    )

    assert appointment.status == "cancelled"
    assert appointment.cancellation_reason == "Me salió trabajo"


@pytest.mark.parametrize("reason", ["Me salió un compromiso de trabajo", None])
async def test_yes_in_the_next_turn_cancels_with_or_without_reason(cancellation, reason):
    ctx, appointment = cancellation
    await tools._handle_cancel_appointment({"appointment_id": str(appointment.id)}, ctx(NOW))

    args = {"appointment_id": str(appointment.id)}
    if reason:
        args["reason"] = reason
    later = ctx(NOW + timedelta(minutes=1))
    result = await tools._handle_cancel_appointment(args, later)

    assert result["success"] is True
    assert appointment.status == "cancelled"
    assert appointment.cancellation_reason == reason
    assert later.state.pending_cancellation is None
    assert _claims_backed("cancel_appointment", result, TOOL_CLAIMS) == {"cancel"}


async def test_a_second_call_in_the_same_turn_still_does_not_cancel(cancellation):
    ctx, appointment = cancellation
    turn = ctx(NOW)
    await tools._handle_cancel_appointment({"appointment_id": str(appointment.id)}, turn)
    result = await tools._handle_cancel_appointment(
        {"appointment_id": str(appointment.id), "reason": "inventado"}, turn
    )

    assert appointment.status == "scheduled"
    assert result["confirmation_needed"] is True


def test_pending_cancellation_is_shown_to_the_model(cancellation):
    ctx, appointment = cancellation
    from app.modules.conversation.state import PendingCancellation

    state = ConversationState(
        pending_cancellation=PendingCancellation(
            appointment_id=str(appointment.id), label="lunes 12 a las 6:00 PM",
            asked_at=NOW.isoformat(),
        )
    )
    assert "todavía NO está cancelada" in state.render()
