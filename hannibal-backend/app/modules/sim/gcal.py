"""The simulator's side of Google Calendar: cleanup, inspection and fixtures.

A simulator reset wipes the database but keeps the calendar link, and Google
does not reset with it. Every event the scenario created stayed in the test
calendar — and Google's freebusy kept reporting those slots as busy after the
appointments behind them were gone. The next run then "found" phantom
conflicts: "mañana a las 4" failed because of a booking from the previous run,
not because of anything the assistant did.

So a reset first deletes, from Google, every event this simulator put there:
the events of the appointments in the database (booked, cancelled or moved)
and the "personal" events scenarios create as fixtures (tracked in Redis).

Only ever deletes events this module can prove are the simulator's: ids read
from its own tables, or — for the one-off purge — events whose description
carries one of the markers the app writes. A doctor's own events never match.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

import httpx
import redis.asyncio as aioredis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Appointment, GoogleCalendarEvent, Office
from app.modules.google_calendar.auth import get_valid_google_token
from app.modules.google_calendar.service import create_calendar_event, delete_calendar_event
from app.utils.logger import get_logger

logger = get_logger(__name__)

# Google event ids of the "personal" events scenarios create (not appointments).
FIXTURE_EVENTS_KEY = "sim:gcal_fixture_events:{office_id}"
FIXTURE_EVENTS_TTL = 30 * 86400

FIXTURE_MARKER = "Evento de prueba del simulador"

# Descriptions the app writes on the events it creates (see the gcal_description
# of every book_appointment caller, and the urgency approval path).
APP_EVENT_MARKERS = (
    "Agendada por WhatsApp",
    "Reagendada por WhatsApp",
    "Agendada por el doctor",
    "Reagendada por el doctor",
    "Agendada desde el dashboard",
    "Cita urgente aprobada por el doctor",
    "Agendada mientras Google Calendar estaba desconectado",
    "Fixture del simulador",
    FIXTURE_MARKER,
)


def calendar_connected(office: Office) -> bool:
    return bool(office.google_calendar_token)


async def _event_ids_in_db(db: AsyncSession, office_id) -> set[str]:
    ids = set(
        (await db.execute(
            select(Appointment.google_event_id).where(
                (Appointment.office_id == office_id)
                & (Appointment.google_event_id.is_not(None))
            )
        )).scalars().all()
    )
    ids |= set(
        (await db.execute(
            select(GoogleCalendarEvent.google_event_id).where(
                (GoogleCalendarEvent.office_id == office_id)
                & (GoogleCalendarEvent.appointment_id.is_not(None))
            )
        )).scalars().all()
    )
    return {i for i in ids if i}


async def delete_simulator_events(
    db: AsyncSession, redis_client: aioredis.Redis, office: Office
) -> dict:
    """Delete from Google every event this scenario created. Best-effort."""
    if not calendar_connected(office):
        return {"deleted": 0, "failed": 0, "skipped": "calendar not connected"}

    key = FIXTURE_EVENTS_KEY.format(office_id=office.id)
    fixture_ids = {
        i.decode() if isinstance(i, bytes) else i
        for i in await redis_client.smembers(key)
    }
    ids = await _event_ids_in_db(db, office.id) | fixture_ids

    deleted = failed = 0
    for event_id in ids:
        try:
            await delete_calendar_event(office.id, event_id, db)
            deleted += 1
        except Exception as e:  # already gone (410) or Google hiccup: keep going
            failed += 1
            logger.warning("sim_gcal_delete_failed", event_id=event_id, error=str(e))
    await redis_client.delete(key)
    logger.info("sim_gcal_events_deleted", deleted=deleted, failed=failed)
    return {"deleted": deleted, "failed": failed}


async def list_events(
    db: AsyncSession, office: Office, time_min: datetime, time_max: datetime
) -> list[dict]:
    """Events in the office's calendar between two instants (expanded, not deleted)."""
    token = await get_valid_google_token(office.id, db)
    calendar_id = office.google_calendar_id or "primary"
    events: list[dict] = []
    page_token: Optional[str] = None
    async with httpx.AsyncClient(timeout=20) as client:
        while True:
            params = {
                "timeMin": time_min.isoformat(),
                "timeMax": time_max.isoformat(),
                "singleEvents": "true",
                "orderBy": "startTime",
                "maxResults": "250",
            }
            if page_token:
                params["pageToken"] = page_token
            r = await client.get(
                f"https://www.googleapis.com/calendar/v3/calendars/{calendar_id}/events",
                headers={"Authorization": f"Bearer {token}"},
                params=params,
            )
            r.raise_for_status()
            body = r.json()
            events.extend(body.get("items", []))
            page_token = body.get("nextPageToken")
            if not page_token:
                return events


async def purge_marked_events(
    db: AsyncSession, office: Office, time_min: datetime, time_max: datetime
) -> dict:
    """One-off cleanup: delete events the APP created (by description marker).

    For calendars that collected events before resets cleaned up after
    themselves. Events without a marker — anything a person created — are left
    alone.
    """
    deleted = kept = 0
    for event in await list_events(db, office, time_min, time_max):
        description = event.get("description") or ""
        if any(marker in description for marker in APP_EVENT_MARKERS):
            try:
                await delete_calendar_event(office.id, event["id"], db)
                deleted += 1
            except Exception as e:
                logger.warning("sim_gcal_purge_failed", event_id=event.get("id"), error=str(e))
        else:
            kept += 1
    return {"deleted": deleted, "kept_not_ours": kept}


async def create_personal_event(
    db: AsyncSession,
    redis_client: aioredis.Redis,
    office: Office,
    start: datetime,
    end: datetime,
    title: str,
) -> str:
    """A busy event straight in Google, as if the doctor had added it himself."""
    event_id = await create_calendar_event(
        office_id=office.id,
        title=title,
        start_time=start,
        end_time=end,
        description=FIXTURE_MARKER,
        db=db,
        color_id="8",
    )
    key = FIXTURE_EVENTS_KEY.format(office_id=office.id)
    await redis_client.sadd(key, event_id)
    await redis_client.expire(key, FIXTURE_EVENTS_TTL)
    return event_id
