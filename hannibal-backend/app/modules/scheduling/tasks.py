"""Celery tasks for scheduling notifications (doctor reschedule notice)."""

from __future__ import annotations

import asyncio
from uuid import UUID

import redis.asyncio as aioredis
from celery import shared_task

from app.config import settings
from app.db.base import get_async_session_maker
from app.modules.scheduling.reschedule_notify import notify_doctor_of_reschedule
from app.utils.logger import get_logger

logger = get_logger(__name__)

# Small delay so the patient booking transaction commits before the notify task
# (running in a separate process/session) tries to load the appointment. If the
# turn runs longer than this, the task retries on "not_found" (see below).
NOTIFY_COUNTDOWN_SECONDS = 10
NOTIFY_RETRY_DELAY_SECONDS = 10
NOTIFY_MAX_RETRIES = 5


def _log(msg: str) -> None:
    logger.info("celery_task", detail=msg)


def _log_exception(task_name: str, e: Exception) -> None:
    logger.error("celery_task_failed", task=task_name, error=str(e), exc_info=True)


def enqueue_reschedule_notification(new_appointment_id: UUID) -> None:
    """Schedule the doctor reschedule notification (after the booking commits)."""
    notify_doctor_reschedule_task.apply_async(
        args=[str(new_appointment_id)], countdown=NOTIFY_COUNTDOWN_SECONDS
    )
    logger.info("reschedule_notification_enqueued", new_appointment_id=str(new_appointment_id))


async def _notify_doctor_reschedule_async(new_appointment_id: str) -> str:
    from app.modules.whatsapp.meta_client import MetaCloudClient

    redis_client = aioredis.from_url(settings.redis_url, decode_responses=True)
    try:
        async with get_async_session_maker()() as db:
            status = await notify_doctor_of_reschedule(
                db, redis_client, MetaCloudClient(), UUID(new_appointment_id)
            )
            await db.commit()
            return status
    finally:
        await redis_client.close()


@shared_task(bind=True, max_retries=NOTIFY_MAX_RETRIES)
def notify_doctor_reschedule_task(self, new_appointment_id: str):
    """Notify the doctor how a patient rescheduled a slot the doctor had cancelled.

    Retries on "not_found" — that means the patient turn that created the new
    appointment hasn't committed yet (a slow LLM turn can outlast the countdown).
    """
    _log(f"notify_doctor_reschedule: START new_appointment_id={new_appointment_id}")
    try:
        status = asyncio.run(_notify_doctor_reschedule_async(new_appointment_id))
    except Exception as e:
        _log_exception("notify_doctor_reschedule", e)
        raise

    if status == "not_found":
        _log(f"notify_doctor_reschedule: appointment not visible yet, retrying id={new_appointment_id}")
        try:
            # Raises Retry (propagates so Celery reschedules) or MaxRetries when exhausted.
            self.retry(countdown=NOTIFY_RETRY_DELAY_SECONDS)
        except self.MaxRetriesExceededError:
            _log(f"notify_doctor_reschedule: gave up (appointment never appeared) id={new_appointment_id}")
        return

    _log(f"notify_doctor_reschedule: DONE ({status}) new_appointment_id={new_appointment_id}")
