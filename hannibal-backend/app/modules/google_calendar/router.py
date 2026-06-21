"""FastAPI router for Google Calendar integration endpoints."""

from __future__ import annotations

from uuid import UUID
import base64

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db, get_current_user, get_redis
from app.db.models import Office
from app.modules.google_calendar.auth import (
    get_google_oauth_url,
    exchange_code_for_token,
)
from app.modules.google_calendar.sync import import_calendar_changes
from app.modules.google_calendar.watch import (
    create_watch_channel,
    delete_watch_channel,
)
from app.utils.logger import get_logger
from sqlalchemy import select
from app.core.exceptions import NotFoundError, GoogleCalendarError

logger = get_logger(__name__)

router = APIRouter(tags=["Google Calendar"])


async def get_office_from_user(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Office:
    """Get office for authenticated user."""
    user_id = current_user.get("sub")
    result = await db.execute(
        select(Office).where(Office.user_id == UUID(user_id))
    )
    office = result.scalar_one_or_none()

    if not office:
        raise NotFoundError("Office not found")

    return office


@router.get("/auth/url")
async def get_oauth_url(
    office: Office = Depends(get_office_from_user),
):
    """
    Get Google OAuth2 authorization URL (requires JWT auth).
    """
    auth_url = get_google_oauth_url(office.id)
    return {"auth_url": auth_url}


@router.get("/setup/{office_id}")
async def setup_oauth_url(
    office_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    Get Google OAuth2 authorization URL without JWT (for initial setup).
    Navigate to the returned URL in your browser to authorize.
    """
    oid = UUID(office_id)
    office = await db.get(Office, oid)
    if not office:
        raise NotFoundError("Office not found")

    from fastapi.responses import RedirectResponse
    auth_url = get_google_oauth_url(office.id)
    return RedirectResponse(url=auth_url)


@router.get("/auth/callback")
async def process_oauth_callback(
    code: str = Query(..., description="OAuth2 authorization code"),
    state: str = Query(..., description="State parameter with office ID"),
    db: AsyncSession = Depends(get_db),
):
    """
    Process Google OAuth2 callback (GET — Google redirects here).
    After exchanging the code, redirects back to the frontend.
    """
    from fastapi.responses import RedirectResponse
    from app.config import settings

    frontend_url = settings.frontend_url or "http://localhost:3000"

    try:
        office_id = UUID(base64.b64decode(state).decode())

        logger.info(
            "process_oauth_callback",
            office_id=str(office_id),
        )

        await exchange_code_for_token(code, office_id, db)

        return RedirectResponse(
            url=f"{frontend_url}/onboarding?gcal=success"
        )

    except Exception as e:
        logger.error("oauth_callback_error", error=str(e))
        return RedirectResponse(
            url=f"{frontend_url}/onboarding?gcal=error"
        )


@router.post("/disconnect")
async def disconnect_google_calendar(
    db: AsyncSession = Depends(get_db),
    office: Office = Depends(get_office_from_user),
):
    """
    Disconnect Google Calendar integration.

    Removes stored credentials and stops watching.
    """
    try:
        logger.info(
            "disconnect_google_calendar",
            office_id=str(office.id),
        )

        # Delete watch channel
        try:
            await delete_watch_channel(office.id, db)
        except Exception as e:
            logger.warning(
                "error_deleting_watch",
                office_id=str(office.id),
                error=str(e),
            )

        # Clear credentials
        office.google_calendar_token = None
        office.google_calendar_id = None
        office.google_watch_channel_id = None
        office.google_watch_resource_id = None
        office.google_watch_expiry = None
        office.google_sync_token = None

        await db.commit()

        return {
            "success": True,
            "message": "Google Calendar disconnected",
        }

    except Exception as e:
        logger.error(
            "error_disconnect_google_calendar",
            office_id=str(office.id),
            error=str(e),
        )
        raise GoogleCalendarError(f"Disconnection failed: {str(e)}")


@router.post("/watch/enable")
async def enable_watch(
    webhook_url: str = Query(..., description="Webhook URL for notifications"),
    db: AsyncSession = Depends(get_db),
    office: Office = Depends(get_office_from_user),
):
    """
    Enable push notifications from Google Calendar.

    Query Parameters:
        webhook_url: URL to receive calendar change notifications

    Returns:
        Watch channel ID
    """
    try:
        logger.info(
            "enable_watch",
            office_id=str(office.id),
            webhook_url=webhook_url,
        )

        channel_id = await create_watch_channel(
            office.id,
            webhook_url,
            db,
        )

        return {
            "success": True,
            "channel_id": channel_id,
            "message": "Google Calendar watch enabled",
        }

    except Exception as e:
        logger.error(
            "error_enable_watch",
            office_id=str(office.id),
            error=str(e),
        )
        raise GoogleCalendarError(f"Failed to enable watch: {str(e)}")


@router.post("/watch/disable")
async def disable_watch(
    db: AsyncSession = Depends(get_db),
    office: Office = Depends(get_office_from_user),
):
    """
    Disable push notifications from Google Calendar.
    """
    try:
        logger.info(
            "disable_watch",
            office_id=str(office.id),
        )

        await delete_watch_channel(office.id, db)

        return {
            "success": True,
            "message": "Google Calendar watch disabled",
        }

    except Exception as e:
        logger.error(
            "error_disable_watch",
            office_id=str(office.id),
            error=str(e),
        )
        raise GoogleCalendarError(f"Failed to disable watch: {str(e)}")


async def _process_calendar_push(office_id: UUID) -> None:
    """Background worker: pull and apply Google Calendar changes for an office.

    Runs after the webhook returns 200, with its own DB session and Redis
    client (the request-scoped ones are already closed by then).
    """
    import redis.asyncio as aioredis

    from app.config import settings
    from app.db.base import get_async_session_maker

    redis_client = aioredis.from_url(settings.redis_url, decode_responses=True)
    try:
        async with get_async_session_maker()() as db:
            await import_calendar_changes(office_id, db, redis_client)
    finally:
        await redis_client.close()


@router.post("/webhook")
async def process_calendar_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """
    Webhook endpoint for Google Calendar push notifications.

    This is NOT protected by JWT as it's called by Google's servers. Returns 200
    immediately and syncs the changed events in a background task (Google retries
    on non-2xx, so we must respond fast).
    """
    try:
        headers = dict(request.headers)
        resource_id = headers.get("x-goog-resource-id")
        resource_state = headers.get("x-goog-resource-state")

        logger.info(
            "webhook_received",
            resource_id=resource_id,
            resource_state=resource_state,
        )

        if resource_state == "sync":
            # Initial handshake from Google when the channel is created.
            return {"success": True}

        if not resource_id:
            logger.warning("webhook_missing_resource_id")
            return {"success": True}

        office = (
            await db.execute(
                select(Office).where(Office.google_watch_resource_id == resource_id)
            )
        ).scalar_one_or_none()

        if not office:
            # Stale channel (e.g. office disconnected) — ack so Google stops retrying.
            logger.warning("webhook_office_not_found", resource_id=resource_id)
            return {"success": True}

        background_tasks.add_task(_process_calendar_push, office.id)
        return {"success": True}

    except Exception as e:
        logger.error("webhook_processing_error", error=str(e))
        return {"success": False, "error": str(e)}
