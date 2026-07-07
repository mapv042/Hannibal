"""Celery tasks for Google Calendar integration.

`renew_google_watches` is a Celery Beat task (every 24h): Google Calendar watch
channels expire (~30 days), after which Google silently stops sending push
notifications. This renews channels that are close to expiry so inbound sync
keeps working without manual reconnection.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta

from celery import shared_task
from sqlalchemy import or_, select

from app.db.base import get_async_session_maker
from app.db.models import Office
from app.modules.google_calendar.watch import build_webhook_url, renew_watch_channel
from app.utils.dates import now_mx
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
    cutoff = now_mx() + timedelta(days=RENEWAL_BUFFER_DAYS)
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
        asyncio.run(_renew_google_watches_async())
    except Exception as e:
        _log_exception("renew_google_watches", e)
        raise
