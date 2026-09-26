"""Celery tasks for Google Calendar integration.

`renew_google_watches` is a Celery Beat task (every 24h): Google Calendar watch
channels expire (~30 days), after which Google silently stops sending push
notifications. This renews channels that are close to expiry so inbound sync
keeps working without manual reconnection.
"""

from __future__ import annotations

from datetime import timedelta
from uuid import UUID

from celery import shared_task
from sqlalchemy import or_, select

from app.core.task_runner import run_task
from app.db.base import get_async_session_maker
from app.db.models import Office
from app.modules.google_calendar.watch import build_webhook_url, renew_watch_channel
from app.utils.dates import real_now
from app.utils.logger import get_logger

logger = get_logger(__name__)

# Renew when a channel expires within this window. Beat runs every 24h, so a
# 3-day buffer survives a missed run or two.
RENEWAL_BUFFER_DAYS = 3


def _log(msg: str) -> None:
    logger.info("celery_task", detail=msg)


def _log_exception(task_name: str, e: Exception) -> None:
    logger.error("celery_task_failed", task=task_name, error=str(e), exc_info=True)


async def _renew_google_watches_async() -> None:
    webhook_url = build_webhook_url()
    cutoff = real_now() + timedelta(days=RENEWAL_BUFFER_DAYS)
    renewed = failed = 0

    async with get_async_session_maker()() as db:
        offices = (
            await db.execute(
                select(Office).where(
                    Office.google_calendar_token.isnot(None),
                    or_(
                        Office.google_watch_expiry.is_(None),
                        Office.google_watch_expiry <= cutoff,
                    ),
                )
            )
        ).scalars().all()

        for office in offices:
            try:
                await renew_watch_channel(office.id, webhook_url, db)
                renewed += 1
            except Exception as e:  # one office failing must not block the rest
                failed += 1
                _log(f"renew_google_watches: office={office.id} FAILED: {e}")

    _log(f"renew_google_watches: DONE renewed={renewed} failed={failed}")


@shared_task(bind=True)
def renew_google_watches(self):
    """Beat task: renew Google Calendar watch channels nearing expiry."""
    _log("renew_google_watches: START")
    try:
        run_task(_renew_google_watches_async())
    except Exception as e:
        _log_exception("renew_google_watches", e)
        raise


async def _handle_calendar_auth_failure_async(office_id: str) -> str:
    import redis.asyncio as aioredis

    from app.config import settings
    from app.modules.google_calendar.connection import mark_disconnected_and_notify
    from app.modules.whatsapp.transport import get_meta_client

    redis_client = aioredis.from_url(settings.redis_url, decode_responses=True)
    try:
        async with get_async_session_maker()() as db:
            return await mark_disconnected_and_notify(
                db, redis_client, get_meta_client(), UUID(office_id)
            )
    finally:
        await redis_client.close()


@shared_task(name="app.modules.google_calendar.tasks.handle_calendar_auth_failure")
def handle_calendar_auth_failure(office_id: str) -> None:
    """Google rejected the office's credentials: flag it and tell the doctor."""
    status = run_task(_handle_calendar_auth_failure_async(office_id))
    logger.info("gcal_auth_failure_handled", office_id=office_id, alert=status)


async def _backfill_calendar_events_async(office_id: str) -> dict:
    from app.modules.google_calendar.connection import backfill_missing_events

    async with get_async_session_maker()() as db:
        return await backfill_missing_events(db, UUID(office_id))


@shared_task(name="app.modules.google_calendar.tasks.backfill_calendar_events")
def backfill_calendar_events(office_id: str) -> None:
    """After a reconnect: write to Google the citas booked while disconnected."""
    result = run_task(_backfill_calendar_events_async(office_id))
    logger.info("gcal_backfill_task_done", office_id=office_id, **result)
