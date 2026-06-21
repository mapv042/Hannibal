"""Google Calendar Push Notifications (watch channels) for real-time sync."""

from __future__ import annotations

from uuid import UUID
from datetime import timedelta
import uuid
import httpx

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.models import Office
from app.modules.google_calendar.auth import get_valid_google_token
from app.core.exceptions import GoogleCalendarError
from app.utils.dates import now_mx
from app.utils.logger import get_logger

logger = get_logger(__name__)


def build_webhook_url() -> str:
    """Public URL Google posts calendar push notifications to.

    Built from BACKEND_URL so the renewal task (which has no HTTP request to
    derive a host from) and the router share one source of truth.
    """
    return f"{settings.backend_url.rstrip('/')}/api/google-calendar/webhook"


async def create_watch_channel(
    office_id: UUID,
    webhook_url: str,
    db: AsyncSession,
) -> str:
    """
    Create a watch channel for Google Calendar push notifications.

    Args:
        office_id: Office ID
        webhook_url: URL to receive push notifications
        db: Database session

    Returns:
        Watch channel ID

    Raises:
        GoogleCalendarError: If watch creation fails
    """
    try:
        access_token = await get_valid_google_token(office_id, db)

        office = await db.get(Office, office_id)
        calendar_id = office.google_calendar_id or "primary"

        channel_id = str(uuid.uuid4())
        # Aware datetime: .timestamp() on a naive datetime would assume local
        # time and send Google an expiration offset by the server's UTC offset.
        expiration = int((now_mx() + timedelta(days=29)).timestamp() * 1000)

        watch_body = {
            "id": channel_id,
            "type": "web_hook",
            "address": webhook_url,
            "expiration": str(expiration),
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"https://www.googleapis.com/calendar/v3/calendars/{calendar_id}/watch",
                json=watch_body,
                headers={"Authorization": f"Bearer {access_token}"},
            )

            if response.status_code not in [200, 201]:
                logger.error(
                    "google_watch_failed",
                    status_code=response.status_code,
                    response=response.text,
                )
                raise GoogleCalendarError("Failed to create watch channel")

            watch_data = response.json()
            resource_id = watch_data.get("resourceId")

            # Store watch info in office. resource_id maps inbound push
            # notifications back to this office; reset the sync token so the
            # first push triggers a full incremental sync.
            office.google_watch_channel_id = channel_id
            office.google_watch_resource_id = resource_id
            office.google_watch_expiry = now_mx() + timedelta(days=29)
            office.google_sync_token = None

            await db.commit()

            logger.info(
                "watch_channel_created",
                office_id=str(office_id),
                channel_id=channel_id,
                resource_id=resource_id,
            )

            return channel_id

    except Exception as e:
        logger.error(
            "error_create_watch_channel",
            office_id=str(office_id),
            error=str(e),
        )
        raise


async def delete_watch_channel(
    office_id: UUID,
    db: AsyncSession,
) -> None:
    """
    Stop watching Google Calendar (delete watch channel).

    Args:
        office_id: Office ID
        db: Database session
    """
    try:
        office = await db.get(Office, office_id)

        if not office or not office.google_watch_channel_id:
            logger.warning(
                "no_watch_channel_to_delete",
                office_id=str(office_id),
            )
            return

        access_token = await get_valid_google_token(office_id, db)

        calendar_id = office.google_calendar_id or "primary"

        stop_body = {
            "id": office.google_watch_channel_id,
            "resourceId": f"calendar#{calendar_id}",
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"https://www.googleapis.com/calendar/v3/calendars/{calendar_id}/stop",
                json=stop_body,
                headers={"Authorization": f"Bearer {access_token}"},
            )

            if response.status_code not in [200, 204]:
                logger.error(
                    "google_watch_stop_failed",
                    status_code=response.status_code,
                    response=response.text,
                )
                # Still clear the watch info locally even if remote fails
                pass

        # Clear watch info
        office.google_watch_channel_id = None
        office.google_watch_resource_id = None
        office.google_watch_expiry = None
        office.google_sync_token = None
        await db.commit()

        logger.info(
            "watch_channel_deleted",
            office_id=str(office_id),
        )

    except Exception as e:
        logger.error(
            "error_delete_watch_channel",
            office_id=str(office_id),
            error=str(e),
        )
        raise


async def renew_watch_channel(
    office_id: UUID,
    webhook_url: str,
    db: AsyncSession,
) -> None:
    """
    Renew expiring watch channel.

    Args:
        office_id: Office ID
        webhook_url: Webhook URL
        db: Database session
    """
    try:
        office = await db.get(Office, office_id)

        # Delete old channel
        await delete_watch_channel(office_id, db)

        # Create new channel
        await create_watch_channel(office_id, webhook_url, db)

        logger.info(
            "watch_channel_renewed",
            office_id=str(office_id),
        )

    except Exception as e:
        logger.error(
            "error_renew_watch_channel",
            office_id=str(office_id),
            error=str(e),
        )
        raise
