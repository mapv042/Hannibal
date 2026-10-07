"""Practice health metrics for the dashboard.

The assistant's work is invisible by design: it answers, confirms and reminds
without the doctor watching. These counters are what turns that into something
they can see and judge — "87% confirman su cita" — so the numbers stay few and
plain rather than becoming a metrics panel nobody reads.

A period is compared against the immediately preceding one of the same length,
which is what makes a rate meaningful ("45 citas, 12% más que el mes pasado").
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from typing import Literal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import BookedVia, MX_TIMEZONE
from app.db.models import Appointment, AvailabilitySchedule, Conversation, Message
from app.utils.dates import now_mx

Period = Literal["week", "month", "quarter"]

_PERIOD_DAYS: dict[str, int] = {"week": 7, "month": 30, "quarter": 90}


@dataclass
class PeriodStats:
    """Counts for one window, plus the rates derived from them."""

    total_appointments: int
    confirmed_appointments: int
    attended_appointments: int
    no_show_appointments: int
    cancelled_appointments: int
    total_patients: int
    # Share of appointments the patient explicitly confirmed or attended.
    # Attended counts: a patient who walked in confirmed by showing up, and
    # scoring that as a failure to confirm would understate the assistant.
    confirmation_rate: float | None
    # Share of *expected* appointments the patient never showed up to. A
    # cancelled appointment is excluded: the patient told us, which is the
    # outcome the reminders are for — folding it in would punish the bot for
    # working.
    no_show_rate: float | None


# What the assistant's work would have cost a person, for the "hours saved"
# estimate. Deliberately conservative and shown to the doctor as an estimate:
# a WhatsApp exchange that ends in a booking (read, check the agenda, answer,
# confirm) takes a secretary about 5 minutes; sending one reminder and handling
# its answer about 2.
MINUTES_PER_CONVERSATION = 5
MINUTES_PER_REMINDER = 2


@dataclass
class AssistantActivity:
    """The assistant's own work in a window — the doctor's return on the tool."""

    conversations_handled: int
    booked_by_assistant: int
    rescheduled_by_assistant: int
    # Share of the assistant's bookings made while the office was closed:
    # the ones a secretary would not have caught until the next morning.
    after_hours_pct: float | None
    reminders_sent: int
    hours_saved_estimate: float


def _is_open(local: datetime, schedules: list[AvailabilitySchedule]) -> bool:
    """Whether a local timestamp falls inside the office's weekly hours."""
    db_dow = (local.weekday() + 1) % 7  # DB convention: 0=Sunday
    t = local.time()
    return any(
        s.day_of_week == db_dow and s.start_time <= t < s.end_time
        for s in schedules
        if s.is_active
    )


async def _assistant_activity(
    db: AsyncSession, office_id: UUID, start: datetime, end: datetime
) -> AssistantActivity:
    conversations = (
        await db.execute(
            select(func.count(func.distinct(Message.conversation_id)))
            .join(Conversation, Message.conversation_id == Conversation.id)
            .where(
                (Conversation.office_id == office_id)
                & (Message.direction == "incoming")
                & (Message.created_at >= start)
                & (Message.created_at < end)
            )
        )
    ).scalar() or 0

    reminders = (
        await db.execute(
            select(func.count(Message.id))
            .join(Conversation, Message.conversation_id == Conversation.id)
            .where(
                (Conversation.office_id == office_id)
                & (Message.direction == "outgoing")
                & (Message.extra_metadata["source"].astext == "reminder_task")
                & (Message.created_at >= start)
                & (Message.created_at < end)
            )
        )
    ).scalar() or 0

    # Work done in the window, so by when the row was written, not the visit date.
    written = (
        await db.execute(
            select(Appointment.created_at, Appointment.rescheduled_from).where(
                (Appointment.office_id == office_id)
                & (Appointment.booked_via == BookedVia.PATIENT_ASSISTANT.value)
                & (Appointment.created_at >= start)
                & (Appointment.created_at < end)
            )
        )
    ).all()
    booked = [created for created, moved_from in written if moved_from is None]
    rescheduled = len(written) - len(booked)

    after_hours_pct: float | None = None
    if booked:
        schedules = list(
            (
                await db.execute(
                    select(AvailabilitySchedule).where(AvailabilitySchedule.office_id == office_id)
                )
            ).scalars().all()
        )
        if schedules:
            closed = sum(
                1 for created in booked if not _is_open(created.astimezone(MX_TIMEZONE), schedules)
            )
            after_hours_pct = _rate(closed, len(booked))

    minutes = conversations * MINUTES_PER_CONVERSATION + reminders * MINUTES_PER_REMINDER
    return AssistantActivity(
        conversations_handled=conversations,
        booked_by_assistant=len(booked),
        rescheduled_by_assistant=rescheduled,
        after_hours_pct=after_hours_pct,
        reminders_sent=reminders,
        hours_saved_estimate=round(minutes / 60, 1),
    )


def _rate(numerator: int, denominator: int) -> float | None:
    """Percentage rounded to whole points, or None when there is nothing to rate."""
    if denominator <= 0:
        return None
    return round(numerator * 100 / denominator)


async def _collect(
    db: AsyncSession, office_id: UUID, start: datetime, end: datetime
) -> PeriodStats:
    rows = (
        await db.execute(
            select(Appointment.status, func.count())
            .where(
                (Appointment.office_id == office_id)
                & (Appointment.start_datetime >= start)
                & (Appointment.start_datetime < end)
            )
            .group_by(Appointment.status)
        )
    ).all()
    by_status = {status: count for status, count in rows}

    patients = (
        await db.execute(
            select(func.count(func.distinct(Appointment.patient_id))).where(
                (Appointment.office_id == office_id)
                & (Appointment.start_datetime >= start)
                & (Appointment.start_datetime < end)
            )
        )
    ).scalar() or 0

    confirmed = by_status.get("confirmed", 0)
    attended = by_status.get("completed", 0)
    no_show = by_status.get("no_show", 0)
    cancelled = by_status.get("cancelled", 0)
    total = sum(by_status.values())

    expected = total - cancelled

    return PeriodStats(
        total_appointments=total,
        confirmed_appointments=confirmed,
        attended_appointments=attended,
        no_show_appointments=no_show,
        cancelled_appointments=cancelled,
        total_patients=patients,
        confirmation_rate=_rate(confirmed + attended, expected),
        no_show_rate=_rate(no_show, expected),
    )


async def get_office_stats(
    db: AsyncSession, office_id: UUID, period: Period = "month"
) -> dict:
    """Stats for the current period plus the one before it, for comparison.

    `change_pct` is the change in appointment volume against the previous
    window. It is None when the previous window had none — "infinitely more
    than zero" is not a number worth showing the doctor.
    """
    days = _PERIOD_DAYS.get(period, 30)
    now = now_mx()
    current_start = now - timedelta(days=days)
    previous_start = current_start - timedelta(days=days)

    current = await _collect(db, office_id, current_start, now)
    previous = await _collect(db, office_id, previous_start, current_start)
    assistant = await _assistant_activity(db, office_id, current_start, now)

    change_pct: int | None = None
    if previous.total_appointments > 0:
        change_pct = round(
            (current.total_appointments - previous.total_appointments)
            * 100
            / previous.total_appointments
        )

    return {
        "period": period,
        "period_days": days,
        **asdict(current),
        "previous": asdict(previous),
        "change_pct": change_pct,
        "assistant": asdict(assistant),
    }
