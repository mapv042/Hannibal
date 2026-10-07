"""The ROI card's "fuera de horario" share: office hours on the DB's weekday convention.

AvailabilitySchedule.day_of_week counts from Sunday = 0 while Python's
weekday() counts from Monday = 0; mixing them up would call every Monday
booking "after hours".
"""

from datetime import datetime, time

from app.core.constants import MX_TIMEZONE
from app.db.models import AvailabilitySchedule
from app.modules.offices.stats import _is_open


def _block(dow: int, start: time, end: time, active: bool = True) -> AvailabilitySchedule:
    return AvailabilitySchedule(day_of_week=dow, start_time=start, end_time=end, is_active=active)


# Monday to Friday, 9:00-14:00 and 16:00-19:00.
SCHEDULES = [
    _block(dow, start, end)
    for dow in range(1, 6)
    for start, end in ((time(9), time(14)), (time(16), time(19)))
]


def _mx(y, mo, d, h, mi=0) -> datetime:
    return datetime(y, mo, d, h, mi, tzinfo=MX_TIMEZONE)


def test_monday_morning_is_open():
    assert _is_open(_mx(2026, 9, 28, 10), SCHEDULES)  # Monday


def test_lunch_gap_is_closed():
    assert not _is_open(_mx(2026, 9, 28, 15), SCHEDULES)


def test_closing_time_is_closed():
    assert not _is_open(_mx(2026, 9, 28, 19), SCHEDULES)


def test_sunday_is_closed():
    assert not _is_open(_mx(2026, 9, 27, 11), SCHEDULES)  # Sunday


def test_night_is_closed():
    assert not _is_open(_mx(2026, 9, 29, 23, 30), SCHEDULES)


def test_inactive_block_does_not_count():
    assert not _is_open(_mx(2026, 10, 3, 10), [_block(6, time(9), time(13), active=False)])
