"""Celery tasks for the post-action write audit (Rule 12).

Enqueued right after any path that creates, moves, cancels or re-states an
appointment. The countdown gives the caller's transaction time to commit —
tool handlers commit in the conversation manager, after the task is queued —
and "not_found" retries cover a turn that runs long.
"""

from __future__ import annotations

import asyncio
from typing import Optional
from uuid import UUID

import redis.asyncio as aioredis
from celery import shared_task

from app.config import settings
from app.db.base import get_async_session_maker
from app.modules.audit.service import verify_appointment_write
from app.utils.logger import get_logger

logger = get_logger(__name__)

# Long enough for the booking turn to commit and for Google Calendar to make a
# freshly created event readable; short enough that the doctor hears about a
# problem well before the patient shows up.
AUDIT_COUNTDOWN_SECONDS = 20
AUDIT_RETRY_DELAY_SECONDS = 15
AUDIT_MAX_RETRIES = 5


def enqueue_write_audit(
    appointment_id: UUID,
    action: str,
    *,
    start_datetime=None,
    status: Optional[str] = None,
    patient_id: Optional[UUID] = None,
) -> None:
    """Queue an audit of what an action believes it just wrote.

    `action` is "book" | "reschedule" | "cancel" | "status" — it decides whether
    the Google Calendar event is expected to be present or gone.
    """
    expectation = {
        "action": action,
        "start_datetime": start_datetime.isoformat() if start_datetime else None,
        "status": status,
        "patient_id": str(patient_id) if patient_id else None,
    }
    try:
        verify_appointment_write_task.apply_async(
            args=[str(appointment_id), expectation],
            countdown=AUDIT_COUNTDOWN_SECONDS,
        )
        logger.info(
            "write_audit_enqueued",
            appointment_id=str(appointment_id),
            action=action,
        )
    except Exception as e:
        # Never let the audit break the action it is auditing.
        logger.warning(
            "write_audit_enqueue_failed",
            appointment_id=str(appointment_id),
            error=str(e),
        )


async def _verify_async(appointment_id: str, expectation: dict) -> str:
    from app.modules.whatsapp.meta_client import MetaCloudClient

    redis_client = aioredis.from_url(settings.redis_url, decode_responses=True)
    try:
        async with get_async_session_maker()() as db:
            status = await verify_appointment_write(
                db,
                redis_client,
                MetaCloudClient(),
                UUID(appointment_id),
                expectation,
            )
            await db.commit()
            return status
    finally:
        await redis_client.close()


@shared_task(bind=True, max_retries=AUDIT_MAX_RETRIES)
def verify_appointment_write_task(self, appointment_id: str, expectation: dict):
    """Verify one appointment write against the DB and Google Calendar."""
    logger.info("audit_task_start", appointment_id=appointment_id)
    try:
        status = asyncio.run(_verify_async(appointment_id, expectation))
    except Exception as e:
        logger.error("audit_task_failed", appointment_id=appointment_id, error=str(e), exc_info=True)
        raise

    if status == "not_found":
        try:
            self.retry(countdown=AUDIT_RETRY_DELAY_SECONDS)
        except self.MaxRetriesExceededError:
            # The row never appeared: the action reported success on something
            # that isn't in the database. That is itself the Rule 12 failure.
            logger.error(
                "audit_appointment_never_appeared",
                appointment_id=appointment_id,
                action=expectation.get("action"),
            )
        return

    logger.info("audit_task_done", appointment_id=appointment_id, result=status)
