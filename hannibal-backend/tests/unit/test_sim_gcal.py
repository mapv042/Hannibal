"""Google Calendar pieces of the simulator and the evals (no network)."""

from datetime import date, datetime
from types import SimpleNamespace

from app.modules.sim import gcal as sim_gcal
from tests.evals.scenarios import Result, gcal_invariants


def result(appointments, events):
    return Result(
        monday=date(2026, 9, 28), appointments=appointments, transcript=[], traces=[],
        fixtures={}, whatsapp_id="1", gcal_events=events,
    )


def appt(start, status="scheduled", event="e1", minutes=40):
    return {"start": start, "status": status, "duration_minutes": minutes, "google_event_id": event}


def event(start, end, eid="e1", transparency="opaque", status="confirmed"):
    return {"id": eid, "start": start, "end": end, "transparency": transparency, "status": status}


def test_matching_event_passes():
    r = result([appt("2026-09-29T16:00")], [event("2026-09-29T16:00", "2026-09-29T16:40")])
    assert gcal_invariants(r) == []


def test_missing_event_is_a_failure():
    r = result([appt("2026-09-29T16:00", event=None)], [])
    assert "has no Google Calendar event" in gcal_invariants(r)[0]


def test_event_at_the_wrong_time_is_a_failure():
    r = result([appt("2026-09-29T16:00")], [event("2026-09-29T04:00", "2026-09-29T04:40")])
    assert "doesn't match" in gcal_invariants(r)[0]


def test_cancelled_appointment_must_free_the_slot():
    busy = result([appt("2026-09-29T16:00", status="cancelled")],
                  [event("2026-09-29T16:00", "2026-09-29T16:40")])
    freed = result([appt("2026-09-29T16:00", status="cancelled")],
                   [event("2026-09-29T16:00", "2026-09-29T16:40", transparency="transparent")])
    assert "still blocks" in gcal_invariants(busy)[0]
    assert gcal_invariants(freed) == []


def test_active_but_transparent_event_is_a_failure():
    r = result([appt("2026-09-29T16:00")],
               [event("2026-09-29T16:00", "2026-09-29T16:40", transparency="transparent")])
    assert "doesn't block" in gcal_invariants(r)[0]


async def test_purge_only_touches_events_the_app_created(monkeypatch):
    events = [
        {"id": "a", "description": "Motivo: x\nAgendada por WhatsApp"},
        {"id": "b", "description": "Cita urgente aprobada por el doctor"},
        {"id": "c", "description": "Comida con mi familia"},
        {"id": "d"},  # no description at all: a person made it
        {"id": "e", "description": sim_gcal.FIXTURE_MARKER},
    ]
    deleted = []

    async def fake_list(db, office, time_min, time_max):
        return events

    async def fake_delete(office_id, event_id, db):
        deleted.append(event_id)

    monkeypatch.setattr(sim_gcal, "list_events", fake_list)
    monkeypatch.setattr(sim_gcal, "delete_calendar_event", fake_delete)
    out = await sim_gcal.purge_marked_events(
        None, SimpleNamespace(id="o"), datetime(2026, 9, 1), datetime(2026, 10, 1)
    )
    assert sorted(deleted) == ["a", "b", "e"]
    assert out == {"deleted": 3, "kept_not_ours": 2}
