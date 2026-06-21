"""Google Calendar API operations."""

from __future__ import annotations

from uuid import UUID
from datetime import datetime, timedelta
from typing import Optional
import httpx

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.google_calendar.auth import get_valid_google_token
from app.core.constants import MX_TIMEZONE
from app.core.exceptions import GoogleCalendarError
from app.utils.dates import now_mx
from app.utils.logger import get_logger

logger = get_logger(__name__)

# How far ahead a full (token-less) sync looks for events.
SYNC_HORIZON_DAYS = 60


async def get_freebusy(
    office_id: UUID,
    time_min: datetime,
    time_max: datetime,
    db: AsyncSession,
) -> list[dict]:
    """
    Query Google Calendar freebusy API to get busy periods.

    Returns:
        List of dicts with "start" and "end" ISO strings for busy periods.
    """
    try:
        access_token = await get_valid_google_token(office_id, db)

        from app.db.models import Office
        office = await db.get(Office, office_id)
        calendar_id = office.google_calendar_id or "primary"

        payload = {
            "timeMin": time_min.isoformat(),
            "timeMax": time_max.isoformat(),
            "timeZone": "America/Mexico_City",
            "items": [{"id": calendar_id}],
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://www.googleapis.com/calendar/v3/freeBusy",
                json=payload,
                headers={"Authorization": f"Bearer {access_token}"},
            )

            if response.status_code != 200:
                logger.error(
                    "google_freebusy_failed",
                    status_code=response.status_code,
                    response=response.text,
                )
                raise GoogleCalendarError(
                    f"Google Calendar freebusy query failed (status {response.status_code})"
                )

            data = response.json()
            busy_periods = data.get("calendars", {}).get(calendar_id, {}).get("busy", [])

            logger.info(
                "google_freebusy_success",
                office_id=str(office_id),
                busy_count=len(busy_periods),
            )

            return busy_periods

    except GoogleCalendarError:
        raise
    except Exception as e:
        logger.error(
            "error_get_freebusy",
            office_id=str(office_id),
            error=str(e),
        )
        raise GoogleCalendarError(f"Failed to query Google Calendar: {e}")


class _SyncTokenExpired(Exception):
    """Internal sentinel: Google returned 410 (sync token no longer valid)."""


async def list_events_incremental(
    office_id: UUID,
    db: AsyncSession,
    sync_token: Optional[str],
) -> tuple[list[dict], Optional[str]]:
    """List calendar events that changed since the last sync.

    Uses Google's incremental sync: when a `sync_token` is given, only events
    changed since it are returned (including deletions as `status="cancelled"`).
    With no token (or an expired one — HTTP 410), it falls back to a full list
    over the next SYNC_HORIZON_DAYS to re-seed the token.

    Returns:
        (items, next_sync_token). next_sync_token is None if Google didn't
        return one (shouldn't happen on success), in which case the caller
        keeps its previous token.
    """
    access_token = await get_valid_google_token(office_id, db)

    from app.db.models import Office

    office = await db.get(Office, office_id)
    calendar_id = office.google_calendar_id or "primary"

    base_url = (
        f"https://www.googleapis.com/calendar/v3/calendars/{calendar_id}/events"
    )

    def _base_params() -> dict:
        params = {"singleEvents": "true", "showDeleted": "true", "maxResults": "250"}
        if sync_token:
            params["syncToken"] = sync_token
        else:
            # syncToken is mutually exclusive with timeMin/timeMax.
            params["timeMin"] = now_mx().isoformat()
            params["timeMax"] = (now_mx() + timedelta(days=SYNC_HORIZON_DAYS)).isoformat()
        return params

    async def _fetch(params: dict) -> tuple[list[dict], Optional[str]]:
        items: list[dict] = []
        next_token: Optional[str] = None
        page_token: Optional[str] = None
        async with httpx.AsyncClient() as client:
            while True:
                page_params = dict(params)
                if page_token:
                    page_params["pageToken"] = page_token
                response = await client.get(
                    base_url,
                    params=page_params,
                    headers={"Authorization": f"Bearer {access_token}"},
                )
                if response.status_code == 410:
                    # syncToken expired — signal caller to retry full sync.
                    raise _SyncTokenExpired()
                if response.status_code != 200:
                    logger.error(
                        "google_events_list_failed",
                        status_code=response.status_code,
                        response=response.text,
                    )
                    raise GoogleCalendarError(
                        f"Google Calendar events.list failed (status {response.status_code})"
                    )
                data = response.json()
                items.extend(data.get("items", []))
                next_token = data.get("nextSyncToken") or next_token
                page_token = data.get("nextPageToken")
                if not page_token:
                    break
        return items, next_token

    try:
        items, next_token = await _fetch(_base_params())
    except _SyncTokenExpired:
        logger.warning("google_sync_token_expired", office_id=str(office_id))
        sync_token = None  # force the full-list branch
        items, next_token = await _fetch(_base_params())

    logger.info(
        "google_events_listed",
        office_id=str(office_id),
        count=len(items),
        incremental=bool(sync_token),
    )
    return items, next_token


async def create_calendar_event(
    office_id: UUID,
    title: str,
    start_time: datetime,
    end_time: datetime,
    description: Optional[str],
    db: AsyncSession,
    color_id: str = "9",  # 9=Blueberry(blue/scheduled), 10=Basil(green/confirmed)
    all_day: bool = False,
) -> str:
    """
    Create an event in Google Calendar.

    Args:
        office_id: Office ID
        title: Event title
        start_time: Start time
        end_time: End time
        description: Event description
        db: Database session

    Returns:
        Google Calendar event ID

    Raises:
        GoogleCalendarError: If creation fails
    """
    try:
        access_token = await get_valid_google_token(office_id, db)

        from app.db.models import Office

        office = await db.get(Office, office_id)
        calendar_id = office.google_calendar_id or "primary"

        event = {
            "summary": title,
            "description": description or "",
            "colorId": color_id,
        }
        if all_day:
            # Google all-day events use `date` (no time) and an EXCLUSIVE end date,
            # so the last blocked day must be represented as end_date + 1.
            start_local = start_time.astimezone(MX_TIMEZONE).date()
            end_local = end_time.astimezone(MX_TIMEZONE).date()
            event["start"] = {"date": start_local.isoformat()}
            event["end"] = {"date": (end_local + timedelta(days=1)).isoformat()}
        else:
            event["start"] = {"dateTime": start_time.isoformat(), "timeZone": "America/Mexico_City"}
            event["end"] = {"dateTime": end_time.isoformat(), "timeZone": "America/Mexico_City"}

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"https://www.googleapis.com/calendar/v3/calendars/{calendar_id}/events",
                json=event,
                headers={"Authorization": f"Bearer {access_token}"},
            )

            if response.status_code not in [200, 201]:
                logger.error(
                    "google_calendar_create_failed",
                    status_code=response.status_code,
                    response=response.text,
                )
                raise GoogleCalendarError("Failed to create Google Calendar event")

            event_data = response.json()
            google_event_id = event_data.get("id")

            logger.info(
                "google_event_created",
                office_id=str(office_id),
                google_event_id=google_event_id,
            )

            return google_event_id

    except Exception as e:
        logger.error(
            "error_create_calendar_event",
            office_id=str(office_id),
            error=str(e),
        )
        raise


async def update_event_color(
    office_id: UUID,
    google_event_id: str,
    color_id: str,
    db: AsyncSession,
) -> None:
    """
    Update just the color of a Google Calendar event.

    Args:
        office_id: Office ID
        google_event_id: Google Calendar event ID
        color_id: Google Calendar colorId ("9"=blue/scheduled, "10"=green/confirmed)
        db: Database session
    """
    try:
        access_token = await get_valid_google_token(office_id, db)

        from app.db.models import Office

        office = await db.get(Office, office_id)
        calendar_id = office.google_calendar_id or "primary"

        async with httpx.AsyncClient() as client:
            # PATCH only updates the specified fields
            response = await client.patch(
                f"https://www.googleapis.com/calendar/v3/calendars/{calendar_id}/events/{google_event_id}",
                json={"colorId": color_id},
                headers={"Authorization": f"Bearer {access_token}"},
            )

            if response.status_code not in [200, 204]:
                logger.error(
                    "google_calendar_color_update_failed",
                    status_code=response.status_code,
                    response=response.text,
                )
                raise GoogleCalendarError("Failed to update event color")

            logger.info(
                "google_event_color_updated",
                office_id=str(office_id),
                google_event_id=google_event_id,
                color_id=color_id,
            )

    except Exception as e:
        logger.error(
            "error_update_event_color",
            office_id=str(office_id),
            google_event_id=google_event_id,
            error=str(e),
        )
        raise


async def mark_event_cancelled(
    office_id: UUID,
    google_event_id: str,
    db: AsyncSession,
) -> None:
    """
    Mark a Google Calendar event as cancelled: red color + transparent (frees the slot).

    Args:
        office_id: Office ID
        google_event_id: Google Calendar event ID
        db: Database session
    """
    try:
        access_token = await get_valid_google_token(office_id, db)

        from app.db.models import Office

        office = await db.get(Office, office_id)
        calendar_id = office.google_calendar_id or "primary"

        async with httpx.AsyncClient() as client:
            # First get the current event to preserve title
            get_response = await client.get(
                f"https://www.googleapis.com/calendar/v3/calendars/{calendar_id}/events/{google_event_id}",
                headers={"Authorization": f"Bearer {access_token}"},
            )

            if get_response.status_code != 200:
                logger.warning(
                    "google_event_not_found_for_cancel",
                    google_event_id=google_event_id,
                )
                return

            event = get_response.json()
            original_title = event.get("summary", "Cita")

            # PATCH: red color (11), transparent (frees the time), update title
            response = await client.patch(
                f"https://www.googleapis.com/calendar/v3/calendars/{calendar_id}/events/{google_event_id}",
                json={
                    "colorId": "11",  # Red = Tomato in Google Calendar
                    "transparency": "transparent",  # Frees the time slot
                    "summary": f"[CANCELADA] {original_title}",
                },
                headers={"Authorization": f"Bearer {access_token}"},
            )

            if response.status_code not in [200, 204]:
                logger.error(
                    "google_calendar_cancel_mark_failed",
                    status_code=response.status_code,
                    response=response.text,
                )
                raise GoogleCalendarError("Failed to mark event as cancelled")

            logger.info(
                "google_event_marked_cancelled",
                office_id=str(office_id),
                google_event_id=google_event_id,
            )

    except Exception as e:
        logger.error(
            "error_mark_event_cancelled",
            office_id=str(office_id),
            google_event_id=google_event_id,
            error=str(e),
        )
        raise


async def update_calendar_event(
    office_id: UUID,
    google_event_id: str,
    title: Optional[str] = None,
    start_time: Optional[datetime] = None,
    end_time: Optional[datetime] = None,
    description: Optional[str] = None,
    db: AsyncSession = None,
    all_day: bool = False,
) -> None:
    """
    Update an existing Google Calendar event.

    Args:
        office_id: Office ID
        google_event_id: Google Calendar event ID
        title: New title (optional)
        start_time: New start time (optional)
        end_time: New end time (optional)
        description: New description (optional)
        db: Database session

    Raises:
        GoogleCalendarError: If update fails
    """
    try:
        access_token = await get_valid_google_token(office_id, db)

        from app.db.models import Office

        office = await db.get(Office, office_id)
        calendar_id = office.google_calendar_id or "primary"

        # Get current event first
        async with httpx.AsyncClient() as client:
            get_response = await client.get(
                f"https://www.googleapis.com/calendar/v3/calendars/{calendar_id}/events/{google_event_id}",
                headers={"Authorization": f"Bearer {access_token}"},
            )

            if get_response.status_code != 200:
                raise GoogleCalendarError("Event not found in Google Calendar")

            event = get_response.json()

            # Update fields
            if title:
                event["summary"] = title
            if description is not None:
                event["description"] = description
            if all_day:
                # Replace start/end wholesale so Google never gets both `date` and
                # `dateTime`. End date is exclusive, so add one day to the last day.
                if start_time:
                    event["start"] = {"date": start_time.astimezone(MX_TIMEZONE).date().isoformat()}
                if end_time:
                    end_local = end_time.astimezone(MX_TIMEZONE).date()
                    event["end"] = {"date": (end_local + timedelta(days=1)).isoformat()}
            else:
                if start_time:
                    event["start"]["dateTime"] = start_time.isoformat()
                if end_time:
                    event["end"]["dateTime"] = end_time.isoformat()

            # Perform update
            update_response = await client.put(
                f"https://www.googleapis.com/calendar/v3/calendars/{calendar_id}/events/{google_event_id}",
                json=event,
                headers={"Authorization": f"Bearer {access_token}"},
            )

            if update_response.status_code not in [200, 204]:
                logger.error(
                    "google_calendar_update_failed",
                    status_code=update_response.status_code,
                    response=update_response.text,
                )
                raise GoogleCalendarError("Failed to update Google Calendar event")

            logger.info(
                "google_event_updated",
                office_id=str(office_id),
                google_event_id=google_event_id,
            )

    except Exception as e:
        logger.error(
            "error_update_calendar_event",
            office_id=str(office_id),
            google_event_id=google_event_id,
            error=str(e),
        )
        raise


async def delete_calendar_event(
    office_id: UUID,
    google_event_id: str,
    db: AsyncSession,
) -> None:
    """
    Delete a Google Calendar event.

    Args:
        office_id: Office ID
        google_event_id: Google Calendar event ID
        db: Database session

    Raises:
        GoogleCalendarError: If deletion fails
    """
    try:
        access_token = await get_valid_google_token(office_id, db)

        from app.db.models import Office

        office = await db.get(Office, office_id)
        calendar_id = office.google_calendar_id or "primary"

        async with httpx.AsyncClient() as client:
            response = await client.delete(
                f"https://www.googleapis.com/calendar/v3/calendars/{calendar_id}/events/{google_event_id}",
                headers={"Authorization": f"Bearer {access_token}"},
            )

            if response.status_code not in [200, 204, 404]:
                logger.error(
                    "google_calendar_delete_failed",
                    status_code=response.status_code,
                    response=response.text,
                )
                raise GoogleCalendarError("Failed to delete Google Calendar event")

            logger.info(
                "google_event_deleted",
                office_id=str(office_id),
                google_event_id=google_event_id,
            )

    except Exception as e:
        logger.error(
            "error_delete_calendar_event",
            office_id=str(office_id),
            google_event_id=google_event_id,
            error=str(e),
        )
        raise
