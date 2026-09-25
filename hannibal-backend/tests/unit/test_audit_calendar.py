"""Write audit (Rule 12) against Google Calendar, and Google request retries."""

from datetime import datetime
from types import SimpleNamespace

import httpx
import pytest

from app.core.constants import MX_TIMEZONE
from app.modules.audit import service as audit
from app.modules.google_calendar import service as gcal


def office():
    return SimpleNamespace(id="o1", google_calendar_token={"x": 1})


def appt():
    return SimpleNamespace(
        id="a1", google_event_id="ev1",
        start_datetime=datetime(2026, 9, 30, 9, tzinfo=MX_TIMEZONE),
    )


@pytest.mark.parametrize("event,blocks", [
    (None, False),
    ({"status": "cancelled"}, False),
    ({"status": "confirmed", "transparency": "transparent"}, False),  # how the app cancels
    ({"status": "confirmed"}, True),
    ({"status": "confirmed", "transparency": "opaque"}, True),
])
def test_event_blocks_slot(event, blocks):
    assert audit.event_blocks_slot(event) is blocks


async def test_correct_cancellation_is_not_a_divergence(monkeypatch):
    async def get_event(*a):
        return {"status": "confirmed", "transparency": "transparent", "summary": "[CANCELADA] Cita"}

    monkeypatch.setattr(audit, "get_calendar_event", get_event)
    assert await audit._check_calendar(None, office(), appt(), expected_present=False) is None


async def test_blocking_cancelled_event_is_a_divergence(monkeypatch):
    async def get_event(*a):
        return {"status": "confirmed"}

    monkeypatch.setattr(audit, "get_calendar_event", get_event)
    d = await audit._check_calendar(None, office(), appt(), expected_present=False)
    assert d.kind == audit.KIND_CALENDAR_STALE


async def test_repair_frees_the_slot(monkeypatch):
    state = {"transparency": "opaque"}

    async def mark(office_id, event_id, db):
        state["transparency"] = "transparent"

    async def get_event(*a):
        return {"status": "confirmed", **state}

    monkeypatch.setattr(audit, "mark_event_cancelled", mark)
    monkeypatch.setattr(audit, "get_calendar_event", get_event)
    assert await audit._repair_cancelled_event(None, office(), appt()) is True


async def test_repair_that_fails_reports_false(monkeypatch):
    async def mark(*a):
        raise RuntimeError("google down")

    monkeypatch.setattr(audit, "mark_event_cancelled", mark)
    assert await audit._repair_cancelled_event(None, office(), appt()) is False


async def test_google_request_retries_transient_errors(monkeypatch):
    monkeypatch.setattr("asyncio.sleep", _no_sleep)
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(503 if len(calls) < 3 else 200, json={})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        r = await gcal._request_with_retry(client, "GET", "https://x/y")
    assert r.status_code == 200 and len(calls) == 3


async def test_google_request_does_not_retry_client_errors(monkeypatch):
    monkeypatch.setattr("asyncio.sleep", _no_sleep)
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(404, json={})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        r = await gcal._request_with_retry(client, "GET", "https://x/y")
    assert r.status_code == 404 and len(calls) == 1


async def _no_sleep(*a, **k):
    return None
