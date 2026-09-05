"""Celery tasks for scheduling notifications (doctor reschedule notice)."""

from __future__ import annotations

import asyncio
from uuid import UUID

import redis.asyncio as aioredis
from celery import shared_task

from app.config import settings
from app.db.base import get_async_session_maker
from app.modules.scheduling.patient_notify import (
    alert_doctor_undelivered_notice,
    notify_patient_cancellation,
    notify_patient_reschedule,
)
from app.modules.scheduling.reschedule_notify import (
    notify_doctor_of_abandoned_reschedule,
    notify_doctor_of_reschedule,
)
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


# --------------------------------------------------------------------------- #
# Patient notices for dashboard-initiated changes (Rule 9: never silent)
# --------------------------------------------------------------------------- #

# Unlike the doctor notifications, these retry on a send FAILURE too, not only
# on "not_found": a cancellation the patient never hears about is the exact
# outcome Rule 9 exists to prevent.
PATIENT_NOTICE_MAX_RETRIES = 5
PATIENT_NOTICE_RETRY_DELAY_SECONDS = 60


def enqueue_patient_cancellation_notice(appointment_id: UUID) -> None:
    """Tell the patient their appointment was cancelled from the dashboard."""
    notify_patient_cancellation_task.apply_async(
        args=[str(appointment_id)], countdown=NOTIFY_COUNTDOWN_SECONDS
    )
    logger.info("patient_cancellation_notice_enqueued", appointment_id=str(appointment_id))


def enqueue_patient_reschedule_notice(appointment_id: UUID) -> None:
    """Tell the patient their appointment was moved from the dashboard."""
    notify_patient_reschedule_task.apply_async(
        args=[str(appointment_id)], countdown=NOTIFY_COUNTDOWN_SECONDS
    )
    logger.info("patient_reschedule_notice_enqueued", appointment_id=str(appointment_id))


async def _notify_patient_async(kind: str, appointment_id: str) -> str:
    from app.modules.whatsapp.meta_client import MetaCloudClient

    sender = (
        notify_patient_cancellation if kind == "cancellation" else notify_patient_reschedule
    )
    async with get_async_session_maker()() as db:
        status = await sender(db, MetaCloudClient(), UUID(appointment_id))
        await db.commit()
        return status


def _escalate_undelivered(kind: str, appointment_id: str) -> None:
    """Hand an undeliverable patient notice to the doctor. Never raises."""
    try:
        asyncio.run(_escalate_undelivered_async(kind, appointment_id))
    except Exception as e:
        _log_exception("escalate_undelivered_notice", e)


async def _escalate_undelivered_async(kind: str, appointment_id: str) -> None:
    from app.modules.whatsapp.meta_client import MetaCloudClient

    redis_client = aioredis.from_url(settings.redis_url, decode_responses=True)
    try:
        async with get_async_session_maker()() as db:
            await alert_doctor_undelivered_notice(
                db, redis_client, MetaCloudClient(), UUID(appointment_id), kind
            )
    finally:
        await redis_client.close()


def _run_patient_notice(task, kind: str, appointment_id: str) -> None:
    """Shared body: send, retry on both 'not_found' and a send failure."""
    _log(f"notify_patient_{kind}: START appointment_id={appointment_id}")
    try:
        status = asyncio.run(_notify_patient_async(kind, appointment_id))
    except Exception as e:
        _log_exception(f"notify_patient_{kind}", e)
        try:
            task.retry(countdown=PATIENT_NOTICE_RETRY_DELAY_SECONDS)
        except task.MaxRetriesExceededError:
            # Out of retries: the patient still doesn't know. Rule 9 forbids
            # continuing as if they'd been told, so hand it to the doctor.
            logger.error(
                "patient_notice_undelivered",
                kind=kind,
                appointment_id=appointment_id,
                error=str(e),
            )
            _escalate_undelivered(kind, appointment_id)
        return

    if status == "not_found":
        _log(f"notify_patient_{kind}: appointment not visible yet, retrying id={appointment_id}")
        try:
            task.retry(countdown=NOTIFY_RETRY_DELAY_SECONDS)
        except task.MaxRetriesExceededError:
            logger.error(
                "patient_notice_undelivered",
                kind=kind,
                appointment_id=appointment_id,
                error="appointment never appeared",
            )
            _escalate_undelivered(kind, appointment_id)
        return

    _log(f"notify_patient_{kind}: DONE ({status}) appointment_id={appointment_id}")


@shared_task(bind=True, max_retries=PATIENT_NOTICE_MAX_RETRIES)
def notify_patient_cancellation_task(self, appointment_id: str):
    """Deliver the cancellation notice to the patient."""
    _run_patient_notice(self, "cancellation", appointment_id)


@shared_task(bind=True, max_retries=PATIENT_NOTICE_MAX_RETRIES)
def notify_patient_reschedule_task(self, appointment_id: str):
    """Deliver the reschedule notice to the patient."""
    _run_patient_notice(self, "reschedule", appointment_id)


def enqueue_abandoned_reschedule_notification(cancelled_appointment_id: UUID) -> None:
    """Report to the doctor that a requested reschedule ended in a cancellation."""
    notify_doctor_abandoned_reschedule_task.apply_async(
        args=[str(cancelled_appointment_id)], countdown=NOTIFY_COUNTDOWN_SECONDS
    )
    logger.info(
        "abandoned_reschedule_notification_enqueued",
        cancelled_appointment_id=str(cancelled_appointment_id),
    )


async def _notify_abandoned_reschedule_async(cancelled_appointment_id: str) -> str:
    from app.modules.whatsapp.meta_client import MetaCloudClient

    redis_client = aioredis.from_url(settings.redis_url, decode_responses=True)
    try:
        async with get_async_session_maker()() as db:
            status = await notify_doctor_of_abandoned_reschedule(
                db, redis_client, MetaCloudClient(), UUID(cancelled_appointment_id)
            )
            await db.commit()
            return status
    finally:
        await redis_client.close()


@shared_task(bind=True, max_retries=NOTIFY_MAX_RETRIES)
def notify_doctor_abandoned_reschedule_task(self, cancelled_appointment_id: str):
    """Tell the doctor the patient cancelled instead of rescheduling (Rule 13)."""
    _log(f"notify_abandoned_reschedule: START id={cancelled_appointment_id}")
    try:
        status = asyncio.run(
            _notify_abandoned_reschedule_async(cancelled_appointment_id)
        )
    except Exception as e:
        _log_exception("notify_abandoned_reschedule", e)
        raise

    if status == "not_found":
        try:
            self.retry(countdown=NOTIFY_RETRY_DELAY_SECONDS)
        except self.MaxRetriesExceededError:
            _log(f"notify_abandoned_reschedule: gave up id={cancelled_appointment_id}")
        return

    _log(f"notify_abandoned_reschedule: DONE ({status}) id={cancelled_appointment_id}")
