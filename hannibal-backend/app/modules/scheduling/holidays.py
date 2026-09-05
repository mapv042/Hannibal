"""Mexican statutory holidays as seeded TimeBlocks.

Rule 4 of the self-validation protocol says the assistant must not book on
non-working days. The engine already subtracts TimeBlocks, so a holiday only
needs to exist as one — no new table, no new code path in availability, and the
doctor can delete any of them from the doctor channel like any other block
(plenty of practices do work on 12 de diciembre).

Dates follow the Ley Federal del Trabajo art. 74: some are fixed, three move to
a given Monday. Election day and the sexenio transition are deliberately left
out — they're not annual and would go stale.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, time, timedelta
from typing import List, Tuple

from app.core.constants import BlockOrigin, MX_TIMEZONE
from app.db.models import TimeBlock

# How many years ahead of the office's first day we seed. Two covers the whole
# of the current year plus the next one for an office created in December.
HOLIDAY_SEED_YEARS = 2

# (month, day, name) — fixed-date holidays.
_FIXED_HOLIDAYS: List[Tuple[int, int, str]] = [
    (1, 1, "Año Nuevo"),
    (5, 1, "Día del Trabajo"),
    (9, 16, "Independencia de México"),
    (12, 25, "Navidad"),
]

# (month, weekday, ordinal, name) — weekday 0=Monday. Ordinal is 1-based.
_MOVABLE_HOLIDAYS: List[Tuple[int, int, int, str]] = [
    (2, 0, 1, "Día de la Constitución"),
    (3, 0, 3, "Natalicio de Benito Juárez"),
    (11, 0, 3, "Revolución Mexicana"),
]


def _nth_weekday(year: int, month: int, weekday: int, ordinal: int) -> date:
    """The `ordinal`-th `weekday` of a month (weekday 0=Monday)."""
    first = date(year, month, 1)
    offset = (weekday - first.weekday()) % 7
    return first + timedelta(days=offset + 7 * (ordinal - 1))


def holidays_for_year(year: int) -> List[Tuple[date, str]]:
    """Every statutory holiday in a given year, sorted by date."""
    days = [(date(year, m, d), name) for m, d, name in _FIXED_HOLIDAYS]
    days += [
        (_nth_weekday(year, month, weekday, ordinal), name)
        for month, weekday, ordinal, name in _MOVABLE_HOLIDAYS
    ]
    return sorted(days)


def build_holiday_blocks(
    office_id: uuid.UUID,
    *,
    from_date: date | None = None,
    years: int = HOLIDAY_SEED_YEARS,
) -> List[TimeBlock]:
    """Full-day TimeBlock rows for the upcoming statutory holidays.

    Only holidays on or after `from_date` are produced — seeding an office in
    July shouldn't litter its calendar with blocks it can never use.
    """
    start_from = from_date or datetime.now(tz=MX_TIMEZONE).date()
    blocks: List[TimeBlock] = []

    for offset in range(years):
        for day, name in holidays_for_year(start_from.year + offset):
            if day < start_from:
                continue
            blocks.append(
                TimeBlock(
                    id=uuid.uuid4(),
                    office_id=office_id,
                    start_date=datetime.combine(day, time.min, tzinfo=MX_TIMEZONE),
                    end_date=datetime.combine(day, time.max, tzinfo=MX_TIMEZONE),
                    reason=name,
                    is_all_day=True,
                    origin=BlockOrigin.HOLIDAY.value,
                )
            )

    return blocks
