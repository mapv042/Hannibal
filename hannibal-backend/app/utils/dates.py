from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from app.core.constants import MX_TIMEZONE as MX_TZ


def now_mx() -> datetime:
    """
    Get current time in Mexico City timezone.

    Returns:
        Current datetime in America/Mexico_City timezone
    """
    return datetime.now(tz=MX_TZ)


def to_mx(dt: datetime) -> datetime:
    """
    Convert any datetime to Mexico City timezone.

    Args:
        dt: Datetime object (with or without timezone)

    Returns:
        Datetime in Mexico City timezone
    """
    if dt.tzinfo is None:
        # Assume UTC if no timezone
        dt = dt.replace(tzinfo=ZoneInfo("UTC"))
    return dt.astimezone(MX_TZ)


def format_date(dt: datetime) -> str:
    """
    Format datetime as "Monday, March 10" style date.

    Args:
        dt: Datetime to format

    Returns:
        Formatted date string in English
    """
    # Ensure datetime is in Mexico City timezone
    dt = to_mx(dt)

    # English day names (0=Monday, 6=Sunday)
    weekdays = [
        "Monday",
        "Tuesday",
        "Wednesday",
        "Thursday",
        "Friday",
        "Saturday",
        "Sunday",
    ]

    # English month names
    months = [
        "January",
        "February",
        "March",
        "April",
        "May",
        "June",
        "July",
        "August",
        "September",
        "October",
        "November",
        "December",
    ]

    day_name = weekdays[dt.weekday()]
    day_num = dt.day
    month_name = months[dt.month - 1]

    return f"{day_name}, {month_name} {day_num}"


def format_time(dt: datetime) -> str:
    """
    Format datetime as "10:00am" style time.

    Args:
        dt: Datetime to format

    Returns:
        Formatted time string
    """
    # Ensure datetime is in Mexico City timezone
    dt = to_mx(dt)

    return dt.strftime("%-I:%M%p").lower()
