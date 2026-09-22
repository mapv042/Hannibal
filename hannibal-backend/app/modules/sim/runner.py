"""Moving the simulated clock, and everything that has to happen when it moves.

The offset lives in Redis so the API and the Celery worker agree on what time it
is. Advancing it is not just a write: caches have to be dropped, sessions that
would have expired have to expire, and the reminder sweep has to run — otherwise
the operator moves the clock and nothing happens, which is exactly the confusion
the simulator exists to remove.

Two design rules worth knowing before changing anything here:

**The clock advances in ticks, it does not jump.** Jumping a day and sweeping once
at the end silently loses reminders: the sweep discards anything
`is_still_worth_sending` now considers stale, so a 6h reminder whose appointment
has since passed is dropped without a trace. Stepping through in beat-sized
intervals reproduces what production would actually have sent. It is a handful of
small queries per tick, so a day costs seconds.

**The clock only moves forward.** Google Calendar does not travel in time, so
rewinding would leave us asking it about dates that no longer match the
appointments we wrote. Resetting a scenario means destroying and reseeding.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from typing import Optional
from uuid import UUID

import redis.asyncio as aioredis
from sqlalchemy import select, and_

from app.config import settings
from app.core.clock import set_clock_offset
from app.core.constants import (
    MAX_REMINDER_OFFSET,
    MIN_REMINDER_OFFSET,
    MX_TIMEZONE,
    SENT_FLAG_BY_REMINDER_TYPE,
)
from app.db.base import get_async_session_maker
from app.db.models import Appointment
from app.modules.conversation.session_store import DEFAULT_SESSION_TTL
from app.modules.reminders.scheduler import due_at
from app.modules.reminders.tasks import SWEEPABLE_STATUSES, _dispatch_due_reminders_async
from app.utils.dates import now_mx
from app.utils.logger import get_logger

logger = get_logger(__name__)

# One offset for the whole simulator. It is deliberately not per-office: a
# simulator environment holds exactly one office (the router refuses to run
# otherwise), and the Celery worker has to read this too — its tasks carry an
# appointment id, not an office, so a per-office key would leave the worker
# with no way to know whose clock to load. A worker stuck on real time while
# the API has moved days ahead is the worst possible failure here: reminders
# would be written with the wrong "mañana".
CLOCK_KEY = "sim:clock_offset"

# Matches the Celery beat cadence, so stepping reproduces production's grain.
TICK = timedelta(minutes=5)

# A single request should not be able to walk a year forward.
MAX_ADVANCE = timedelta(days=30)

# Celery's default queue, which is what celery_app's beat schedule targets.
CELERY_QUEUE = "celery"

# How long a tick waits for the worker to catch up before moving on.
DRAIN_TIMEOUT_SECONDS = 15.0
DRAIN_POLL_SECONDS = 0.05


async def _redis() -> aioredis.Redis:
    return aioredis.from_url(settings.redis_url, decode_responses=True)


async def get_offset() -> int:
    """Seconds the simulated clock is ahead of real time."""
    client = await _redis()
    try:
        raw = await client.get(CLOCK_KEY)
    finally:
        await client.aclose()

    return int(raw) if raw else 0


async def load_offset_into_context() -> int:
    """Read the offset from Redis and apply it for the rest of this request/task.

    This is the bridge between the shared source of truth (Redis) and the cheap
    per-call read (`app.core.clock`). Call it once at the start of a unit of work,
    never per timestamp.
    """
    offset = await get_offset()
    set_clock_offset(offset)
    return offset


async def _store_offset(seconds: int) -> None:
    client = await _redis()
    try:
        await client.set(CLOCK_KEY, str(seconds))
    finally:
        await client.aclose()


async def _drop_availability_cache(office_id: UUID) -> int:
    """Invalidate cached availability, which was computed against the old now."""
    client = await _redis()
    deleted = 0
    try:
        async for key in client.scan_iter(match=f"avail_cache:{office_id}:*", count=500):
            await client.delete(key)
            deleted += 1
    finally:
        await client.aclose()

    return deleted


async def _expire_stale_sessions(office_id: UUID) -> int:
    """Drop sessions that would have expired by now in *virtual* time.

    Redis TTLs run on the wall clock, so after a three-day jump a session that
    production would have dropped long ago is still sitting there and the bot
    "remembers" a conversation it could not possibly remember. Every test would
    then lie in the same direction.

    `SessionContext.last_message_at` is already written with `now_mx()`, so it is
    virtual time and this is a straight comparison.
    """
    import json

    client = await _redis()
    expired = 0
    cutoff = now_mx() - timedelta(seconds=DEFAULT_SESSION_TTL)
    try:
        async for key in client.scan_iter(match=f"session:*:{office_id}", count=500):
            raw = await client.get(key)
            if not raw:
                continue
            try:
                last = datetime.fromisoformat(json.loads(raw)["last_message_at"])
            except (KeyError, ValueError, TypeError):
                continue
            if last.tzinfo is None:
                last = last.replace(tzinfo=MX_TIMEZONE)
            if last < cutoff:
                await client.delete(key)
                expired += 1
    finally:
        await client.aclose()

    return expired


async def _drain_queue() -> bool:
    """Wait until the worker has taken everything this tick queued.

    Production gets this for free: its ticks are five real minutes apart, so by
    the next sweep the worker has long since run the tasks and set each
    appointment's `sent` flag. Simulated ticks land milliseconds apart, so
    without waiting the sweep laps the worker and re-dispatches reminders whose
    flag has not been written yet — the send tasks are idempotent so nothing
    reaches the patient twice, but the queue thrashes and the run reports
    reminders it did not really cause.

    Returns:
        True if the queue drained, False if it timed out (a worker that is down
        or wedged — worth surfacing rather than hanging the request).
    """
    client = await _redis()
    waited = 0.0
    try:
        while waited < DRAIN_TIMEOUT_SECONDS:
            if await client.llen(CELERY_QUEUE) == 0:
                # Queue empty means taken, not necessarily finished; one more
                # short pause lets the in-flight task commit its flag.
                await asyncio.sleep(DRAIN_POLL_SECONDS * 4)
                if await client.llen(CELERY_QUEUE) == 0:
                    return True
            await asyncio.sleep(DRAIN_POLL_SECONDS)
            waited += DRAIN_POLL_SECONDS
    finally:
        await client.aclose()

    logger.warning("sim_queue_drain_timeout", seconds=DRAIN_TIMEOUT_SECONDS)
    return False


async def next_event_at(office_id: UUID) -> Optional[datetime]:
    """When the next reminder for this office comes due, or None if nothing is pending.

    Pure arithmetic over `due_at` — it asks the schedule when something happens
    without running it, which is what lets the UI offer "skip to the next event"
    instead of making the operator guess how far to jump.
    """
    from app.modules.reminders.rules import get_active_reminder_rules

    now = now_mx()
    horizon = now + MAX_ADVANCE

    async with get_async_session_maker()() as db:
        appointments = (
            await db.execute(
                select(Appointment).where(
                    and_(
                        Appointment.office_id == office_id,
                        Appointment.start_datetime
                        >= now - timedelta(minutes=MAX_REMINDER_OFFSET) - timedelta(days=1),
                        Appointment.start_datetime
                        <= horizon + timedelta(minutes=abs(MIN_REMINDER_OFFSET)),
                        Appointment.status.in_(SWEEPABLE_STATUSES),
                    )
                )
            )
        ).scalars().all()

        if not appointments:
            return None

        rules = await get_active_reminder_rules(db, office_id)
        soonest: Optional[datetime] = None

        for appointment in appointments:
            start_local = appointment.start_datetime.astimezone(MX_TIMEZONE)
            for reminder_type, offset_minutes in rules:
                flag = SENT_FLAG_BY_REMINDER_TYPE.get(reminder_type)
                if flag is None or getattr(appointment, flag, False):
                    continue
                due = due_at(reminder_type, offset_minutes, start_local)
                if due is None or due <= now:
                    continue
                if soonest is None or due < soonest:
                    soonest = due

    return soonest


async def advance_clock(office_id: UUID, seconds: int) -> dict:
    """Move this office's clock forward, running everything the move implies.

    Args:
        office_id: The office whose clock moves.
        seconds: How far forward, in seconds. Must be positive.

    Returns:
        A summary: the new offset, the new virtual time, how many caches and
        sessions were cleared, and every reminder dispatched along the way.

    Raises:
        ValueError: If `seconds` is not positive or exceeds MAX_ADVANCE.
    """
    if seconds <= 0:
        raise ValueError("the simulated clock only moves forward")
    if seconds > MAX_ADVANCE.total_seconds():
        raise ValueError(f"cannot advance more than {MAX_ADVANCE.days} days at once")

    start_offset = await get_offset()
    target_offset = start_offset + seconds
    dispatched: list[dict] = []
    drained_cleanly = True
    ticks = 0

    offset = start_offset
    while offset < target_offset:
        offset = min(offset + int(TICK.total_seconds()), target_offset)
        await _store_offset(offset)
        set_clock_offset(offset)
        ticks += 1

        # Order matters: stale availability and sessions must be gone *before*
        # the sweep runs, or it decides against data from the old now.
        await _drop_availability_cache(office_id)
        await _expire_stale_sessions(office_id)

        just_dispatched = await _dispatch_due_reminders_async()
        if just_dispatched:
            # Let the worker run them before the next tick sweeps again, or the
            # sweep re-dispatches what it just queued. See _drain_queue.
            if not await _drain_queue():
                drained_cleanly = False
            dispatched.extend(just_dispatched)

    logger.info(
        "sim_clock_advanced",
        office_id=str(office_id),
        seconds=seconds,
        ticks=ticks,
        dispatched=len(dispatched),
    )

    result = {
        "offset_seconds": offset,
        "now": now_mx().isoformat(),
        "ticks": ticks,
        "dispatched": dispatched,
    }
    if not drained_cleanly:
        result["warning"] = (
            "the Celery queue did not drain within the timeout — is the worker "
            "running? Reminders may be reported more than once."
        )
    return result


async def advance_to_next_event(office_id: UUID) -> dict:
    """Jump to the moment the next reminder comes due, and let it fire.

    Returns the same summary as `advance_clock`, plus `skipped` when there was
    nothing pending to move to.
    """
    target = await next_event_at(office_id)
    if target is None:
        return {
            "offset_seconds": await get_offset(),
            "now": now_mx().isoformat(),
            "ticks": 0,
            "dispatched": [],
            "skipped": "nothing due within the horizon",
        }

    # A second past the due time, so the sweep sees it as due rather than pending.
    seconds = int((target - now_mx()).total_seconds()) + 1
    return await advance_clock(office_id, max(seconds, 1))
