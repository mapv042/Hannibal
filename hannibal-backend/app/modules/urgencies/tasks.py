"""Celery tasks for the urgency flow: notify the doctor and the timeout fallback."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from uuid import UUID

import redis.asyncio as aioredis
from celery import shared_task

from app.config import settings
from app.core.constants import MX_TIMEZONE, URGENCY_APPROVAL_TIMEOUT_MINUTES
from app.db.base import get_async_session_maker
from app.modules.urgencies.service import (
    expire_urgency_request,
    notify_doctor_of_urgency,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)

# Small delay so the patient request transaction commits before the notify task
# (running in a separate process/session) tries to load the request. If the turn
# runs longer than this, the task retries on "not_found" (see below).
NOTIFY_COUNTDOWN_SECONDS = 10
NOTIFY_RETRY_DELAY_SECONDS = 10
NOTIFY_MAX_RETRIES = 5


def _log(msg: str) -> None:
    logger.info("celery_task", detail=msg)


def _log_exception(task_name: str, e: Exception) -> None:
    logger.error("celery_task_failed", task=task_name, error=str(e), exc_info=True)


def enqueue_urgency_flow(request_id: UUID) -> None:
    """Schedule the doctor notification (soon) and the timeout fallback (later)."""
    notify_doctor_urgency_task.apply_async(
        args=[str(request_id)], countdown=NOTIFY_COUNTDOWN_SECONDS
    )
    run_at = datetime.now(MX_TIMEZONE) + timedelta(minutes=URGENCY_APPROVAL_TIMEOUT_MINUTES)
    expire_urgency_request_task.apply_async(args=[str(request_id)], eta=run_at)
    logger.info("urgency_flow_enqueued", request_id=str(request_id), timeout_at=run_at.isoformat())


async def _notify_doctor_urgency_async(request_id: str) -> str:
    from app.modules.whatsapp.meta_client import MetaCloudClient

    redis_client = aioredis.from_url(settings.redis_url, decode_responses=True)
    try:
        async with get_async_session_maker()() as db:
            status = await notify_doctor_of_urgency(db, redis_client, MetaCloudClient(), UUID(request_id))
            await db.commit()
            return status
    finally:
        await redis_client.close()


async def _expire_urgency_request_async(request_id: str) -> None:
    from app.modules.whatsapp.meta_client import MetaCloudClient

    redis_client = aioredis.from_url(settings.redis_url, decode_responses=True)
    try:
        async with get_async_session_maker()() as db:
            await expire_urgency_request(db, redis_client, MetaCloudClient(), UUID(request_id))
            await db.commit()
    finally:
        await redis_client.close()


@shared_task(bind=True, max_retries=NOTIFY_MAX_RETRIES)
def notify_doctor_urgency_task(self, request_id: str):
    """Notify the doctor of a pending urgent request via WhatsApp.

    Retries on "not_found" — that means the patient turn that created the
    request hasn't committed yet (a slow LLM turn can outlast the countdown).
    """
    _log(f"notify_doctor_urgency: START request_id={request_id}")
    try:
        status = asyncio.run(_notify_doctor_urgency_async(request_id))
    except Exception as e:
        _log_exception("notify_doctor_urgency", e)
        raise

    if status == "not_found":
        _log(f"notify_doctor_urgency: request not visible yet, retrying request_id={request_id}")
        try:
            # Raises Retry (propagates so Celery reschedules) or MaxRetries when exhausted.
            self.retry(countdown=NOTIFY_RETRY_DELAY_SECONDS)
        except self.MaxRetriesExceededError:
            _log(f"notify_doctor_urgency: gave up (request never appeared) request_id={request_id}")
        return

    _log(f"notify_doctor_urgency: DONE ({status}) request_id={request_id}")


@shared_task(bind=True)
def expire_urgency_request_task(self, request_id: str):
    """Timeout fallback: offer the patient a normal slot if still pending."""
    _log(f"expire_urgency_request: START request_id={request_id}")
    try:
        asyncio.run(_expire_urgency_request_async(request_id))
        _log(f"expire_urgency_request: DONE request_id={request_id}")
    except Exception as e:
        _log_exception("expire_urgency_request", e)
        raise
