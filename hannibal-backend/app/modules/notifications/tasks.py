"""Celery tasks for the configurable doctor notifications.

Per-event tasks (new appointment, cancellation) are enqueued from the patient
tool handlers with a short countdown so the tool's DB commit (which happens in
the conversation manager after the tool loop) lands first; they retry on
"not_found" if the turn is still in flight.

`send_unconfirmed_summaries` is a Celery Beat task (every 15 min): for each
office it sends the day's unconfirmed-appointments digest once, 1h before the
doctor's first availability block that day.
"""

from __future__ import annotations

import asyncio
import sys
import traceback
from datetime import datetime, timedelta
from uuid import UUID

import redis.asyncio as aioredis
from celery import shared_task
from sqlalchemy import select

from app.config import settings
from app.core.constants import MX_TIMEZONE
from app.db.base import get_async_session_maker
from app.db.models import AvailabilitySchedule, Office
from app.modules.notifications.service import (
    notify_appointment,
    notify_cancellation,
    notify_unconfirmed_summary,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)

# Mirror the urgency/reschedule timing: a small delay so the patient turn commits
# before the notify task (separate process/session) loads the row; retry on
# "not_found" covers slow LLM turns that outlast the countdown.
NOTIFY_COUNTDOWN_SECONDS = 10
NOTIFY_RETRY_DELAY_SECONDS = 10
NOTIFY_MAX_RETRIES = 5

# How long the per-office "already sent today" guard lives (1 day).
UNCONFIRMED_FLAG_TTL_SECONDS = 24 * 60 * 60
UNCONFIRMED_FLAG_KEY = "unconfirmed_summary_sent:{office_id}:{date}"


def _log(msg: str) -> None:
    print(f"[CELERY] {msg}", file=sys.stderr, flush=True)


def _log_exception(task_name: str, e: Exception) -> None:
    _log(f"{task_name} FAILED: {e}")
    traceback.print_exc(file=sys.stderr)
    sys.stderr.flush()


# --------------------------------------------------------------------------- #
# Per-event notifications (enqueued from tool handlers)
# --------------------------------------------------------------------------- #

def enqueue_appointment_notification(appointment_id: UUID, is_new_patient: bool) -> None:
    """Schedule the new-appointment (and/or new-patient) doctor notification."""
    notify_appointment_task.apply_async(
        args=[str(appointment_id), is_new_patient], countdown=NOTIFY_COUNTDOWN_SECONDS
    )
    logger.info("appointment_notification_enqueued", appointment_id=str(appointment_id))


def enqueue_cancellation_notification(appointment_id: UUID) -> None:
    """Schedule the cancellation doctor notification."""
    notify_cancellation_task.apply_async(
        args=[str(appointment_id)], countdown=NOTIFY_COUNTDOWN_SECONDS
    )
    logger.info("cancellation_notification_enqueued", appointment_id=str(appointment_id))


async def _notify_appointment_async(appointment_id: str, is_new_patient: bool) -> str:
    from app.modules.whatsapp.meta_client import MetaCloudClient

    redis_client = aioredis.from_url(settings.redis_url, decode_responses=True)
    try:
        async with get_async_session_maker()() as db:
            status = await notify_appointment(
                db, redis_client, MetaCloudClient(), UUID(appointment_id), is_new_patient
            )
            await db.commit()
            return status
    finally:
        await redis_client.close()


async def _notify_cancellation_async(appointment_id: str) -> str:
    from app.modules.whatsapp.meta_client import MetaCloudClient

    redis_client = aioredis.from_url(settings.redis_url, decode_responses=True)
    try:
        async with get_async_session_maker()() as db:
            status = await notify_cancellation(
                db, redis_client, MetaCloudClient(), UUID(appointment_id)
            )
            await db.commit()
            return status
    finally:
        await redis_client.close()


@shared_task(bind=True, max_retries=NOTIFY_MAX_RETRIES)
def notify_appointment_task(self, appointment_id: str, is_new_patient: bool):
    """Notify the doctor of a newly booked appointment. Retries on 'not_found'."""
    _log(f"notify_appointment: START appointment_id={appointment_id}")
    try:
        status = asyncio.run(_notify_appointment_async(appointment_id, is_new_patient))
    except Exception as e:
        _log_exception("notify_appointment", e)
        raise

    if status == "not_found":
        _log(f"notify_appointment: appointment not visible yet, retrying id={appointment_id}")
        try:
            self.retry(countdown=NOTIFY_RETRY_DELAY_SECONDS)
        except self.MaxRetriesExceededError:
            _log(f"notify_appointment: gave up (appointment never appeared) id={appointment_id}")
        return

    _log(f"notify_appointment: DONE ({status}) appointment_id={appointment_id}")


@shared_task(bind=True, max_retries=NOTIFY_MAX_RETRIES)
def notify_cancellation_task(self, appointment_id: str):
    """Notify the doctor of a patient cancellation. Retries on 'not_found'."""
    _log(f"notify_cancellation: START appointment_id={appointment_id}")
    try:
        status = asyncio.run(_notify_cancellation_async(appointment_id))
    except Exception as e:
        _log_exception("notify_cancellation", e)
        raise

    if status == "not_found":
        _log(f"notify_cancellation: appointment not visible yet, retrying id={appointment_id}")
        try:
            self.retry(countdown=NOTIFY_RETRY_DELAY_SECONDS)
        except self.MaxRetriesExceededError:
            _log(f"notify_cancellation: gave up (appointment never appeared) id={appointment_id}")
        return

    _log(f"notify_cancellation: DONE ({status}) appointment_id={appointment_id}")


# --------------------------------------------------------------------------- #
# Daily unconfirmed-appointments digest (Celery Beat, every 15 min)
# --------------------------------------------------------------------------- #

async def _first_block_start_today(db, office_id, weekday_db: int):
    """Earliest AvailabilitySchedule start_time for office on today's weekday, or None.

    weekday_db follows the model convention 0=Sun..6=Sat.
    """
    result = await db.execute(
        select(AvailabilitySchedule.start_time)
        .where(
            (AvailabilitySchedule.office_id == office_id)
            & (AvailabilitySchedule.day_of_week == weekday_db)
        )
        .order_by(AvailabilitySchedule.start_time.asc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def _send_unconfirmed_summaries_async() -> None:
    from app.modules.whatsapp.meta_client import MetaCloudClient

    redis_client = aioredis.from_url(settings.redis_url, decode_responses=True)
    meta_client = MetaCloudClient()
    now = datetime.now(MX_TIMEZONE)
    # Model stores day_of_week as 0=Sun..6=Sat; isoweekday() is 1=Mon..7=Sun.
    weekday_db = now.isoweekday() % 7

    try:
        async with get_async_session_maker()() as db:
            offices = (
                await db.execute(
                    select(Office).where(
                        (Office.is_active == True)  # noqa: E712
                        & (Office.notify_unconfirmed == True)  # noqa: E712
                    )
                )
            ).scalars().all()

            for office in offices:
                start_time = await _first_block_start_today(db, office.id, weekday_db)
                if start_time is None:
                    continue  # office doesn't work today

                target = datetime.combine(now.date(), start_time, tzinfo=MX_TIMEZONE) - timedelta(hours=1)
                if now < target:
                    continue  # too early

                flag_key = UNCONFIRMED_FLAG_KEY.format(office_id=office.id, date=now.date().isoformat())
                if await redis_client.exists(flag_key):
                    continue  # already handled today

                status = await notify_unconfirmed_summary(db, redis_client, meta_client, office)
                await db.commit()
                # Mark handled for the day even when "skipped" (nothing to send),
                # so we don't recompute every 15 min.
                await redis_client.set(flag_key, now.isoformat(), ex=UNCONFIRMED_FLAG_TTL_SECONDS)
                _log(f"unconfirmed_summary: office={office.id} status={status}")
    finally:
        await redis_client.close()


@shared_task(bind=True)
def send_unconfirmed_summaries(self):
    """Beat task: send each office its daily unconfirmed-appointments digest."""
    _log("send_unconfirmed_summaries: START")
    try:
        asyncio.run(_send_unconfirmed_summaries_async())
        _log("send_unconfirmed_summaries: DONE")
    except Exception as e:
        _log_exception("send_unconfirmed_summaries", e)
        raise
