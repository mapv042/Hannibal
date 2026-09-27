"""A reminder whose moment passed before the appointment was booked is not owed."""

from datetime import datetime, timedelta

from app.core.constants import MX_TIMEZONE
from app.modules.reminders.scheduler import due_at, was_due_after_booking

START = datetime(2026, 9, 29, 11, 40, tzinfo=MX_TIMEZONE)   # Tuesday 11:40 AM


def test_week_before_is_skipped_for_a_cita_booked_two_days_ahead():
    booked = datetime(2026, 9, 27, 13, 4, tzinfo=MX_TIMEZONE)   # the reported case
    due = due_at("week_before", -10080, START)
    assert due < booked
    assert not was_due_after_booking(due, booked)


def test_day_before_is_skipped_for_a_same_day_booking():
    booked = START - timedelta(hours=5)
    assert not was_due_after_booking(due_at("day_before", -1440, START), booked)


def test_reminders_due_after_booking_still_go_out():
    booked = datetime(2026, 9, 10, 9, 0, tzinfo=MX_TIMEZONE)   # booked 19 days ahead
    for rtype, offset in (("week_before", -10080), ("day_before", -1440), ("6h", -360)):
        due = due_at(rtype, offset, START)
        assert due is not None and was_due_after_booking(due, booked), rtype


def test_legacy_rows_without_booking_time_keep_the_old_behavior():
    assert was_due_after_booking(START - timedelta(days=7), None)
