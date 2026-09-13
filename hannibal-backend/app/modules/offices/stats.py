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

from app.core.constants import MX_TIMEZONE
from app.db.models import Appointment

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
    now = datetime.now(MX_TIMEZONE)
    current_start = now - timedelta(days=days)
    previous_start = current_start - timedelta(days=days)

    current = await _collect(db, office_id, current_start, now)
    previous = await _collect(db, office_id, previous_start, current_start)

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
    }
