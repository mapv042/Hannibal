"""Beat task: offer freed slots to the people on each office's waitlist."""

from __future__ import annotations

import redis.asyncio as aioredis
from celery import shared_task
from sqlalchemy import select

from app.config import settings
from app.core.task_runner import run_task
from app.db.base import get_async_session_maker
from app.db.models import Office, WaitlistEntry
from app.modules.waitlist.service import ACTIVE, sweep_office
from app.utils.logger import get_logger

logger = get_logger(__name__)


async def _offer_waitlist_slots_async() -> int:
    from app.modules.whatsapp.transport import get_meta_client

    redis_client = aioredis.from_url(settings.redis_url, decode_responses=True)
    meta_client = get_meta_client()
    offers = 0
    try:
        async with get_async_session_maker()() as db:
            office_ids = (
                await db.execute(
                    select(WaitlistEntry.office_id)
                    .where(WaitlistEntry.status.in_(ACTIVE))
                    .distinct()
                )
            ).scalars().all()
            for office_id in office_ids:
                office = await db.get(Office, office_id)
                if office is None or not office.is_active:
                    continue
                try:
                    offers += await sweep_office(db, redis_client, meta_client, office)
                except Exception as e:  # one office failing must not stop the rest
                    await db.rollback()
                    logger.error("waitlist_sweep_office_failed", office_id=str(office_id), error=str(e))
    finally:
        await redis_client.close()
    return offers


@shared_task(name="app.modules.waitlist.tasks.offer_waitlist_slots")
def offer_waitlist_slots() -> None:
    """Every few minutes: offer freed slots, recycle unanswered offers, expire old wishes."""
    offers = run_task(_offer_waitlist_slots_async())
    logger.info("waitlist_sweep_done", offers=offers)
