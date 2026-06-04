"""Per-office reminder rule loading and seeding.

A reminder rule decides which reminders an office sends and when, relative to
the appointment start (see ReminderType). Offices without explicit rows fall
back to DEFAULT_REMINDER_RULES so the system keeps working out of the box.
"""

from __future__ import annotations

from typing import List, Tuple
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import DEFAULT_REMINDER_RULES
from app.db.models import ReminderRule


def default_reminder_rules() -> List[ReminderRule]:
    """Build a fresh set of default ReminderRule rows (unattached to an office)."""
    return [
        ReminderRule(reminder_type=rtype.value, offset_minutes=offset, enabled=True)
        for rtype, offset in DEFAULT_REMINDER_RULES
    ]


async def get_active_reminder_rules(
    db: AsyncSession, office_id: UUID
) -> List[Tuple[str, int]]:
    """
    Return the office's enabled reminders as (reminder_type, offset_minutes).

    Falls back to DEFAULT_REMINDER_RULES when the office has no rows yet.
    """
    result = await db.execute(
        select(ReminderRule).where(
            ReminderRule.office_id == office_id,
            ReminderRule.enabled == True,  # noqa: E712
        )
    )
    rules = result.scalars().all()
    if rules:
        return [(r.reminder_type, r.offset_minutes) for r in rules]
    return [(rtype.value, offset) for rtype, offset in DEFAULT_REMINDER_RULES]
