"""Core availability engine for appointment scheduling."""

from __future__ import annotations

from datetime import datetime, date, timedelta, time
from typing import List, NamedTuple, Optional, Tuple
from uuid import UUID
import json

import redis.asyncio as aioredis
from sqlalchemy import select, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    AvailabilitySchedule,
    Appointment,
    GoogleCalendarEvent,
    TimeBlock,
    Office,
)
from app.modules.scheduling.schemas import AvailableSlot
from app.modules.google_calendar.service import CalendarEvent, list_busy_events
from app.core.constants import MX_TIMEZONE
from app.core.exceptions import GoogleCalendarAuthError, GoogleCalendarError
from app.utils.dates import now_mx, time_label
from app.utils.logger import get_logger

logger = get_logger(__name__)

ACTIVE_STATUSES = ("scheduled", "confirmed")


class DayAvailability(NamedTuple):
    """Result of computing a day's free slots.

    `has_schedule` distinguishes "no working hours configured for this weekday"
    (False) from "configured but fully booked" (empty slots, True), so callers
    can word their message correctly.
    """

    slots: List[AvailableSlot]
    has_schedule: bool


# What a busy interval came from. The distinction exists so a deliberate
# doctor overbook can stack a patient on top of another cita without also
# steamrolling something the doctor's calendar says is taken:
#   - "appointment": another of our citas (from the appointments table, or the
#     event in Google that mirrors one of our active citas). Soft — the doctor
#     may overbook it.
#   - "google": an event on the doctor's Google Calendar that is NOT one of our
#     citas (a personal commitment, a meeting, a trip). Hard: Google Calendar
#     is the source of truth for the doctor's time — if it says the hour is
#     taken, nobody books it, from either channel or the dashboard.
#   - "time_block": vacations, lunch, anything the doctor blocked. Hard.
BUSY_APPOINTMENT = "appointment"
BUSY_GOOGLE = "google"
BUSY_TIME_BLOCK = "time_block"

# Conflict kinds a deliberate overbook (allow_conflict) is allowed to ignore.
OVERRIDABLE_CONFLICTS = frozenset({BUSY_APPOINTMENT})

# TimeBlock origin of the events copied from Google by the inbound sync.
GOOGLE_MIRROR_ORIGIN = "google_calendar"


class BusyRange(NamedTuple):
    """A tz-aware busy interval and what produced it.

    `label` says what it is in words the doctor recognises ("«Junta» en tu
    Google Calendar"); only the doctor's flow shows it — patients never see
    what the doctor's time is taken by.
    """

    start: datetime
    end: datetime
    kind: str
    label: Optional[str] = None


class SlotConflict(NamedTuple):
    """Why a slot can't be booked.

    `kind` is one of the BUSY_* constants plus "outside_hours"/"no_schedule";
    `message` is the Spanish text meant to reach the patient or doctor;
    `detail` (doctor-facing only) names what the slot collides with.
    """

    kind: str
    message: str
    detail: Optional[str] = None


class GoogleView(NamedTuple):
    """What the doctor's Google Calendar says about a time range.

    `status`:
      - "ok": read live; `external` and `own_active` are authoritative.
      - "not_connected": the office has no calendar connected.
      - "disconnected": Google rejects the office's credentials — scheduling
        falls back to the system's own agenda (see connection.py).
    `external`: events that are not one of our citas (the doctor's own).
    `own_active`: events that mirror one of our active citas, wherever Google
      has them now (the doctor may have dragged one before the sync caught up).
    """

    status: str
    external: List[CalendarEvent]
    own_active: List[CalendarEvent]


def _maybe_uuid(value: str) -> Optional[UUID]:
    try:
        return UUID(hex=value) if len(value) == 32 else None
    except ValueError:
        return None


async def _classify_events(
    office_id: UUID,
    events: List[CalendarEvent],
    db: AsyncSession,
    ignore_appointment_id: Optional[UUID] = None,
) -> Tuple[List[CalendarEvent], List[CalendarEvent]]:
    """Split Google events into the doctor's own commitments and our citas.

    An event is one of our citas when an appointment of this office carries its
    id (`google_event_id`) or was created with it (`calendar_event_id_for`, the
    appointment id's hex). Events of citas no longer active (cancelled, moved,
    past) are dropped: they are stale mirrors the audit repairs, not the
    doctor's time. Blocks the system itself wrote to Google are dropped too:
    their TimeBlock row already counts. So is the event of
    `ignore_appointment_id`, the cita being moved (see check_slot_bookable).
    """
    if not events:
        return [], []
    ids = [e.id for e in events]
    uuid_ids = [u for u in (_maybe_uuid(i) for i in ids) if u is not None]

    conditions = [Appointment.google_event_id.in_(ids)]
    if uuid_ids:
        conditions.append(Appointment.id.in_(uuid_ids))
    appointments = (await db.execute(
        select(Appointment).where(
            and_(Appointment.office_id == office_id, or_(*conditions))
        )
    )).scalars().all()
    status_by_event: dict[str, str] = {}
    moving: set[str] = set()
    for a in appointments:
        for event_id in (a.google_event_id, a.id.hex):
            if event_id:
                if ignore_appointment_id is not None and a.id == ignore_appointment_id:
                    moving.add(event_id)
                # An active row wins over a cancelled one sharing the event
                # (a move in Google hands the event to the new row).
                if status_by_event.get(event_id) not in ACTIVE_STATUSES:
                    status_by_event[event_id] = a.status

    own_blocks = set((await db.execute(
        select(GoogleCalendarEvent.google_event_id).where(
            and_(
                GoogleCalendarEvent.office_id == office_id,
                GoogleCalendarEvent.google_event_id.in_(ids),
                GoogleCalendarEvent.appointment_id.is_(None),
            )
        )
    )).scalars().all())

    external: List[CalendarEvent] = []
    own_active: List[CalendarEvent] = []
    for e in events:
        if e.id in moving:
            continue
        status = status_by_event.get(e.id)
        if status is not None:
            if status in ACTIVE_STATUSES:
                own_active.append(e)
            continue
        if e.id in own_blocks:
            continue
        external.append(e)
    return external, own_active


async def read_google_calendar(
    office_id: UUID,
    time_min: datetime,
    time_max: datetime,
    db: AsyncSession,
    ignore_appointment_id: Optional[UUID] = None,
) -> GoogleView:
    """Read the doctor's Google Calendar for a range — the source of truth.

    Rejected credentials degrade to "disconnected" (and the doctor is told to
    reconnect); any other failure raises GoogleCalendarError, because "I
    couldn't check" must never read as "it's free".
    """
    office = await db.get(Office, office_id)
    if not office or not office.google_calendar_token:
        return GoogleView("not_connected", [], [])

    from app.modules.google_calendar import connection

    if connection.should_skip_google(office_id):
        logger.info("google_calendar_skipped_disconnected", office_id=str(office_id))
        return GoogleView("disconnected", [], [])
    try:
        events = await list_busy_events(
            office_id=office_id, time_min=time_min, time_max=time_max, db=db,
        )
    except GoogleCalendarAuthError as e:
        # Google rejected the credentials: keep scheduling on the system's own
        # agenda and tell the doctor to reconnect. A transient failure
        # (timeout, 5xx) is a GoogleCalendarError and propagates.
        connection.report_auth_failure(office_id, e)
        return GoogleView("disconnected", [], [])
    external, own_active = await _classify_events(
        office_id, events, db, ignore_appointment_id
    )
    return GoogleView("ok", external, own_active)


def google_event_label(event: CalendarEvent) -> str:
    """How a Google event is named to the doctor: «Junta» de 1:00 PM a 2:00 PM."""
    if event.all_day:
        return f"«{event.summary}» (todo el día) en tu Google Calendar"
    return (
        f"«{event.summary}» de {time_label(event.start)} a {time_label(event.end)} "
        "en tu Google Calendar"
    )


async def _collect_busy_ranges(
    office_id: UUID,
    day_start: datetime,
    day_end: datetime,
    db: AsyncSession,
    *,
    google_required: bool,
    ignore_appointment_id: Optional[UUID] = None,
) -> List[BusyRange]:
    """All tz-aware busy intervals for a day: Google + appointments + blocks.

    Google Calendar comes first and is authoritative: every event that occupies
    time there blocks the slot. When it was read live, the TimeBlock copies the
    inbound sync made of Google events are skipped — Google itself already said
    what is busy, and a stale copy of an event the doctor deleted must not keep
    the hour taken. Those copies only count when Google can't be read (the
    credentials were rejected), as the best record of the doctor's calendar.

    `ignore_appointment_id` leaves out one cita — and its event in Google —
    the one being moved: it is cancelled in the same transaction that books
    its new time, so it can't be what that new time collides with.
    """
    busy: List[BusyRange] = []

    google = await read_google_calendar(
        office_id, day_start, day_end, db, ignore_appointment_id
    )
    if google.status == "not_connected" and google_required:
        # Dashboard/engine path requires a connected calendar before scheduling.
        raise GoogleCalendarError(
            "Google Calendar is not configured for this office. "
            "Please connect Google Calendar before scheduling."
        )
    for e in google.external:
        busy.append(BusyRange(e.start, e.end, BUSY_GOOGLE, google_event_label(e)))
    for e in google.own_active:
        busy.append(BusyRange(e.start, e.end, BUSY_APPOINTMENT))
    if google.status == "ok":
        logger.info(
            "google_calendar_applied",
            office_id=str(office_id),
            external=len(google.external),
            own=len(google.own_active),
        )

    # Existing appointments (scheduled/confirmed)
    appointments = (await db.execute(
        select(Appointment).where(
            and_(
                Appointment.office_id == office_id,
                Appointment.start_datetime >= day_start,
                Appointment.start_datetime <= day_end,
                Appointment.status.in_(ACTIVE_STATUSES),
            )
        )
    )).scalars().all()
    for a in appointments:
        if ignore_appointment_id is not None and a.id == ignore_appointment_id:
            continue
        a_start = a.start_datetime
        a_end = a.end_datetime
        if a_start.tzinfo is None:
            a_start = a_start.replace(tzinfo=MX_TIMEZONE)
        if a_end is None:
            a_end = a_start + timedelta(minutes=a.duration_minutes or 30)
        elif a_end.tzinfo is None:
            a_end = a_end.replace(tzinfo=MX_TIMEZONE)
        busy.append(BusyRange(a_start, a_end, BUSY_APPOINTMENT))

    # Time blocks overlapping the day (vacations, manual blocks, holidays; the
    # copies of Google events only when Google itself couldn't be read)
    block_filter = [
        TimeBlock.office_id == office_id,
        TimeBlock.start_date <= day_end,
        TimeBlock.end_date >= day_start,
    ]
    if google.status == "ok":
        block_filter.append(TimeBlock.origin != GOOGLE_MIRROR_ORIGIN)
    blocks = (await db.execute(select(TimeBlock).where(and_(*block_filter)))).scalars().all()
    for b in blocks:
        b_start = b.start_date
        b_end = b.end_date
        if b_start.tzinfo is None:
            b_start = b_start.replace(tzinfo=MX_TIMEZONE)
        if b_end.tzinfo is None:
            b_end = b_end.replace(tzinfo=MX_TIMEZONE)
        busy.append(BusyRange(b_start, b_end, BUSY_TIME_BLOCK, b.reason or None))

    return busy


async def compute_day_availability(
    office_id: UUID,
    date_: date,
    db: AsyncSession,
    *,
    slot_minutes: Optional[int] = None,
    redis_client: Optional[aioredis.Redis] = None,
    only_future: bool = False,
    google_required: bool = False,
    ignore_appointment_id: Optional[UUID] = None,
) -> DayAvailability:
    """Single availability engine shared by the dashboard and both WhatsApp bots.

    All datetimes are tz-aware (Mexico City) so slots can be compared against
    appointment/block/Google intervals without naive-vs-aware errors.

    Args:
        slot_minutes: slot length to lay out; None uses each schedule's own
            appointment_duration_min (the configured grid the bots display).
        redis_client: when provided, read/write the 5-min availability cache.
        only_future: drop slots that already started (use for "today").
        google_required: raise GoogleCalendarError when no calendar is connected
            (dashboard behavior); the bots pass False and simply skip it.
        ignore_appointment_id: the cita being moved — its own time (and its
            Google event) doesn't take slots away from it, so a move can land
            on an hour that overlaps where it is now. Bypasses the cache, which
            holds the office-wide view.
    """
    if ignore_appointment_id is not None:
        redis_client = None
    # Schedules for that weekday (DB convention: Sun=0..Sat=6)
    db_day_of_week = (date_.weekday() + 1) % 7
    schedules = (await db.execute(
        select(AvailabilitySchedule).where(
            and_(
                AvailabilitySchedule.office_id == office_id,
                AvailabilitySchedule.day_of_week == db_day_of_week,
                AvailabilitySchedule.is_active == True,
            )
        )
    )).scalars().all()
    if not schedules:
        logger.info("no_schedules_for_date", office_id=str(office_id), date=str(date_))
        return DayAvailability([], has_schedule=False)

    # Cache (only when a client is provided; key is per office+date, slots are
    # filtered by the requested length on read).
    cache_key = f"avail_cache:{office_id}:{date_}"
    if redis_client is not None:
        try:
            cached = await redis_client.get(cache_key)
            if cached:
                cached_slots = [AvailableSlot(**s) for s in json.loads(cached)]
                if slot_minutes is not None:
                    cached_slots = [
                        s for s in cached_slots
                        if (s.end_time - s.start_time).total_seconds() / 60 >= slot_minutes
                    ]
                logger.info("availability_cache_hit", office_id=str(office_id), date=str(date_))
                return DayAvailability(cached_slots, has_schedule=True)
        except Exception as e:
            logger.warning("cache_read_error", error=str(e))

    # Candidate grid (tz-aware MX). Slot length is the requested one, or the
    # schedule's configured duration when not specified.
    candidates: List[Tuple[datetime, datetime]] = []
    for schedule in schedules:
        length = slot_minutes if slot_minutes is not None else schedule.appointment_duration_min
        step = length + schedule.buffer_minutes
        cursor = datetime.combine(date_, schedule.start_time, tzinfo=MX_TIMEZONE)
        end_of_day = datetime.combine(date_, schedule.end_time, tzinfo=MX_TIMEZONE)
        while cursor + timedelta(minutes=length) <= end_of_day:
            candidates.append((cursor, cursor + timedelta(minutes=length)))
            cursor += timedelta(minutes=step)

    if not candidates:
        return DayAvailability([], has_schedule=True)

    day_start = datetime.combine(date_, time.min, tzinfo=MX_TIMEZONE)
    day_end = datetime.combine(date_, time.max, tzinfo=MX_TIMEZONE)
    busy = await _collect_busy_ranges(
        office_id, day_start, day_end, db,
        google_required=google_required,
        ignore_appointment_id=ignore_appointment_id,
    )

    now = now_mx()
    available: List[AvailableSlot] = []
    # Why each candidate was dropped. A false "no hay espacios" is otherwise
    # undiagnosable: this says whether an appointment, a block or a Google
    # event (often an all-day one marked busy) ate the day.
    removed = {"past": 0, BUSY_APPOINTMENT: 0, BUSY_TIME_BLOCK: 0, BUSY_GOOGLE: 0}
    for start, end in candidates:
        if only_future and start <= now:
            removed["past"] += 1
            continue
        overlapping = [b for b in busy if not (end <= b.start or start >= b.end)]
        if overlapping:
            kinds = {b.kind for b in overlapping}
            for kind in (BUSY_TIME_BLOCK, BUSY_GOOGLE, BUSY_APPOINTMENT):
                if kind in kinds:
                    removed[kind] += 1
                    break
            continue
        available.append(AvailableSlot(start_time=start, end_time=end))

    if redis_client is not None:
        try:
            cache_data = [
                {"start_time": s.start_time.isoformat(), "end_time": s.end_time.isoformat()}
                for s in available
            ]
            await redis_client.setex(cache_key, 300, json.dumps(cache_data))
        except Exception as e:
            logger.warning("cache_write_error", error=str(e))

    logger.info(
        "availability_generated",
        office_id=str(office_id),
        date=str(date_),
        candidates=len(candidates),
        slots_count=len(available),
        removed_past=removed["past"],
        removed_by_appointment=removed[BUSY_APPOINTMENT],
        removed_by_time_block=removed[BUSY_TIME_BLOCK],
        removed_by_google=removed[BUSY_GOOGLE],
    )
    return DayAvailability(available, has_schedule=True)


async def check_slot_bookable(
    office_id: UUID,
    start_dt: datetime,
    end_dt: datetime,
    db: AsyncSession,
    *,
    ignore_appointment_id: Optional[UUID] = None,
) -> Optional[SlotConflict]:
    """Validate that a concrete slot can be booked right now.

    Checks that the slot falls inside the office's working hours for that
    weekday and that nothing on the doctor's Google Calendar (the source of
    truth), no other appointment and no time block overlaps it. An office
    without a connected calendar is checked against the system's own agenda.

    Returns None when bookable, or a SlotConflict when not. The `kind` lets a
    caller decide what a deliberate overbook may ignore (see
    OVERRIDABLE_CONFLICTS); `message` is the Spanish text for the user;
    `detail` names the colliding event for the doctor.

    Hard conflicts (a block, an event of the doctor's in Google) are reported
    before another cita, so a deliberate overbook can never slip past them.

    `ignore_appointment_id` is the cita a reschedule replaces: moving 10:00 →
    10:30 must not collide with itself (it is cancelled in the same
    transaction that books the new time).
    """
    date_ = start_dt.astimezone(MX_TIMEZONE).date()

    db_day_of_week = (date_.weekday() + 1) % 7
    schedules = (await db.execute(
        select(AvailabilitySchedule).where(
            and_(
                AvailabilitySchedule.office_id == office_id,
                AvailabilitySchedule.day_of_week == db_day_of_week,
                AvailabilitySchedule.is_active == True,  # noqa: E712
            )
        )
    )).scalars().all()
    if not schedules:
        return SlotConflict(
            "no_schedule", "No hay horario de atención configurado para ese día."
        )

    in_working_hours = False
    for schedule in schedules:
        window_start = datetime.combine(date_, schedule.start_time, tzinfo=MX_TIMEZONE)
        window_end = datetime.combine(date_, schedule.end_time, tzinfo=MX_TIMEZONE)
        if start_dt >= window_start and end_dt <= window_end:
            in_working_hours = True
            break
    if not in_working_hours:
        return SlotConflict(
            "outside_hours",
            "El horario está fuera del horario de atención del consultorio.",
        )

    day_start = datetime.combine(date_, time.min, tzinfo=MX_TIMEZONE)
    day_end = datetime.combine(date_, time.max, tzinfo=MX_TIMEZONE)
    busy = await _collect_busy_ranges(
        office_id, day_start, day_end, db,
        google_required=False,
        ignore_appointment_id=ignore_appointment_id,
    )

    overlapping = [
        b for b in busy if not (end_dt <= b.start or start_dt >= b.end)
    ]
    if not overlapping:
        return None

    # Hard conflicts outrank another cita: report them even if an appointment
    # also overlaps, so a deliberate overbook can't slip past them.
    for b in overlapping:
        if b.kind == BUSY_TIME_BLOCK:
            return SlotConflict(
                BUSY_TIME_BLOCK,
                "Ese horario está bloqueado en la agenda del doctor.",
                f"Bloqueo: {b.label}" if b.label else None,
            )
    for b in overlapping:
        if b.kind == BUSY_GOOGLE:
            return SlotConflict(
                BUSY_GOOGLE,
                "Ese horario está ocupado en el calendario del doctor.",
                b.label,
            )
    return SlotConflict(BUSY_APPOINTMENT, "El horario ya está ocupado por otra cita.")


async def get_available_slots(
    office_id: UUID,
    date_: date,
    duration_min: int,
    db: AsyncSession,
    redis_client: aioredis.Redis,
) -> List[AvailableSlot]:
    """Available slots of length `duration_min` for a date (dashboard/engine).

    Thin wrapper over compute_day_availability that preserves the historical
    behavior: caches, requires Google Calendar, returns just the slot list.
    """
    result = await compute_day_availability(
        office_id,
        date_,
        db,
        slot_minutes=duration_min,
        redis_client=redis_client,
        google_required=True,
    )
    return result.slots


async def invalidate_availability_cache(
    office_id: UUID,
    date_: date,
    redis_client: aioredis.Redis,
) -> None:
    """
    Invalidate availability cache for a given date.

    Args:
        office_id: Office ID
        date_: Date to invalidate
        redis_client: Redis client
    """
    cache_key = f"avail_cache:{office_id}:{date_}"
    try:
        await redis_client.delete(cache_key)
        logger.info(
            "cache_invalidated",
            office_id=str(office_id),
            date=str(date_),
        )
    except Exception as e:
        logger.warning("cache_delete_error", error=str(e))


async def invalidate_office_availability_cache(
    office_id: UUID,
    redis_client: aioredis.Redis,
) -> None:
    """Drop every cached day of an office.

    For changes that move the whole grid (the weekly hours, durations or
    buffer): without it the assistant keeps offering the old hours until each
    day's cache expires.
    """
    try:
        keys = [
            k async for k in redis_client.scan_iter(match=f"avail_cache:{office_id}:*", count=500)
        ]
        if keys:
            await redis_client.delete(*keys)
        logger.info("office_cache_invalidated", office_id=str(office_id), keys=len(keys))
    except Exception as e:
        logger.warning("office_cache_delete_error", office_id=str(office_id), error=str(e))


async def lock_slot_temporarily(
    office_id: UUID,
    start_time: datetime,
    redis_client: aioredis.Redis,
    ttl: int = 60,
) -> bool:
    """
    Temporarily lock a slot to prevent race conditions.

    Uses Redis SETNX for atomic operation.

    Args:
        office_id: Office ID
        start_time: Slot start time
        redis_client: Redis client
        ttl: Lock TTL in seconds (default 60)

    Returns:
        True if lock acquired, False if already locked
    """
    lock_key = f"slot_lock:{office_id}:{start_time.isoformat()}"
    try:
        result = await redis_client.set(
            lock_key, "1", nx=True, ex=ttl
        )
        if result:
            logger.info("slot_locked", office_id=str(office_id), slot=lock_key)
        return result is not None
    except Exception as e:
        logger.error("slot_lock_error", error=str(e))
        return False


async def release_slot_lock(
    office_id: UUID,
    start_time: datetime,
    redis_client: aioredis.Redis,
) -> None:
    """
    Release a temporary slot lock.

    Args:
        office_id: Office ID
        start_time: Slot start time
        redis_client: Redis client
    """
    lock_key = f"slot_lock:{office_id}:{start_time.isoformat()}"
    try:
        await redis_client.delete(lock_key)
        logger.info(
            "slot_unlocked", office_id=str(office_id), slot=lock_key
        )
    except Exception as e:
        logger.warning("slot_unlock_error", error=str(e))


async def get_upcoming_slots(
    office_id: UUID,
    days: int,
    db: AsyncSession,
    redis_client: aioredis.Redis,
) -> List[AvailableSlot]:
    """
    Get all available slots for the next N days.

    Args:
        office_id: Office ID
        days: Number of days to check (default 7)
        db: Database session
        redis_client: Redis client

    Returns:
        List of available slots sorted by date, starting from now: today's
        slots that already started are left out (the urgency timeout used to
        offer 9, 10 and 11 AM at 1:49 PM).
    """
    all_slots = []
    now = now_mx()
    today = now.date()  # Mexico City date, not the server's UTC date

    for i in range(days):
        check_date = today + timedelta(days=i)
        slots = await get_available_slots(
            office_id=office_id,
            date_=check_date,
            duration_min=30,  # Default to 30 min
            db=db,
            redis_client=redis_client,
        )
        all_slots.extend(slot for slot in slots if slot.start_time > now)

    logger.info(
        "upcoming_slots_generated",
        office_id=str(office_id),
        days=days,
        total_slots=len(all_slots),
    )

    return all_slots
