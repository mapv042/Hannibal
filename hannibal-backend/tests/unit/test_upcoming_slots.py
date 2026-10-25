"""Upcoming slots never include today's slots that already started (ARGOS P27)."""

import uuid
from datetime import datetime, timedelta

from app.core.constants import MX_TIMEZONE
from app.modules.scheduling import availability
from app.modules.scheduling.schemas import AvailableSlot

NOW = datetime(2026, 10, 12, 13, 49, tzinfo=MX_TIMEZONE)


async def test_todays_past_slots_are_dropped(monkeypatch):
    async def day_slots(office_id, date_, duration_min, db, redis_client):
        return [
            AvailableSlot(
                start_time=datetime.combine(date_, datetime.min.time(), tzinfo=MX_TIMEZONE)
                + timedelta(hours=h),
                end_time=datetime.combine(date_, datetime.min.time(), tzinfo=MX_TIMEZONE)
                + timedelta(hours=h, minutes=30),
            )
            for h in (9, 10, 11, 16)
        ]

    monkeypatch.setattr(availability, "now_mx", lambda: NOW)
    monkeypatch.setattr(availability, "get_available_slots", day_slots)

    slots = await availability.get_upcoming_slots(uuid.uuid4(), 2, db=None, redis_client=None)

    starts = [s.start_time for s in slots]
    assert all(start > NOW for start in starts)
    assert starts[0] == NOW.replace(hour=16, minute=0)
    assert len(starts) == 5  # today's 16:00 + all four tomorrow
