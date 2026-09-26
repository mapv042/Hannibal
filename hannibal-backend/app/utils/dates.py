from __future__ import annotations

from datetime import date as date_cls, datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from app.core.clock import clock_offset
from app.core.constants import DAYS_ES, MONTHS_ES, MX_TIMEZONE as MX_TZ

# How many days the reference calendar injected into the LLM prompts spans.
# Two weeks covers "el próximo martes" and "la otra semana"; anything further is
# looked up through the availability tool, which answers with real weekdays, and
# bookings are made from the slot ids it returns — so the model never has to do
# date arithmetic to get a booking right.
DATE_REFERENCE_DAYS = 14

# Relative labels for the first days of the reference calendar.
_RELATIVE_LABELS = {0: "hoy", 1: "mañana", 2: "pasado mañana"}


def build_date_reference_block(now: datetime, days: int = DATE_REFERENCE_DAYS) -> str:
    """Build the shared date block injected into both LLM system prompts.

    LLMs have no clock and are unreliable at date arithmetic, so we hand them a
    ready-made lookup table (the next `days` days mapped to their weekday) plus a
    firm "today" anchor. The model looks dates up instead of computing them; for
    anything beyond the table it computes from HOY and the availability tool
    echoes back the real weekday so mistakes surface. Single source of truth for
    the patient and doctor prompts.
    """
    today = now.date()
    lines = [
        f"FECHA Y HORA ACTUAL: {long_date_label(today, today)} ({today.isoformat()}), {time_label(now)}",
        "ZONA HORARIA: Centro de México (CST)",
        "",
        f"CALENDARIO DE REFERENCIA (próximos {days} días — usa estas fechas tal cual, NO las recalcules):",
    ]
    for i in range(days):
        day = today + timedelta(days=i)
        label = _RELATIVE_LABELS.get(i)
        prefix = f"{label}: " if label else ""
        lines.append(f"- {prefix}{long_date_label(day, today)} = {day.isoformat()}")
    lines.append("")
    lines.append(
        "Cuando te pidan un día con palabras (\"el miércoles\", \"el próximo martes\", "
        "\"el 5\"), no lo conviertas tú: pásalo tal cual a la herramienta de disponibilidad "
        "(when), que calcula la fecha exacta y te avisa si es ambigua. Este calendario es "
        "para ubicarte y para leer las fechas que te devuelven las herramientas."
    )
    return "\n".join(lines)


def long_date_label(target_date: date_cls, today: Optional[date_cls] = None) -> str:
    """'jueves 24 de septiembre' (plus the year when it isn't the current one).

    The one way dates are written to patients and to the model. Month names
    instead of 24/09 because a numeric date is read day-first by some people and
    month-first by others, and because the model copies whatever form it is
    shown — so what it is shown must already be the unambiguous one.
    """
    label = f"{DAYS_ES[target_date.weekday()]} {target_date.day} de {MONTHS_ES[target_date.month - 1]}"
    reference_year = (today or now_mx().date()).year
    if target_date.year != reference_year:
        label += f" de {target_date.year}"
    return label


def time_label(dt) -> str:
    """'4:00 PM' — 12-hour clock, the form patients use and the prompts ask for.

    Accepts a datetime or a time. The model is never asked to convert between
    24- and 12-hour forms itself: that conversion is where "las 4" became 04:00.
    """
    hour = dt.hour % 12 or 12
    suffix = "AM" if dt.hour < 12 else "PM"
    return f"{hour}:{dt.minute:02d} {suffix}"


def relative_day_label(target_date: date_cls, today: date_cls) -> Optional[str]:
    """Return 'hoy'/'mañana' when target_date is today/tomorrow, else None.

    Used to ground tool results so the LLM doesn't treat a relative term
    ('mañana') and its absolute date ('miércoles 17') as two different days.
    """
    delta = (target_date - today).days
    if delta == 0:
        return "hoy"
    if delta == 1:
        return "mañana"
    return None


def spanish_date_label(target_date: date_cls, today: date_cls) -> str:
    """'mañana (miércoles 17 de junio)' or 'jueves 18 de junio' if not hoy/mañana."""
    absolute = long_date_label(target_date, today)
    relative = relative_day_label(target_date, today)
    return f"{relative} ({absolute})" if relative else absolute


def now_mx() -> datetime:
    """Current time in Mexico City, and the only place the app reads the clock.

    Call this instead of `datetime.now(MX_TIMEZONE)` anywhere — a bare
    `datetime.now` is a second source of truth that the conversation simulator
    cannot move, so a flow using one would keep running in real time while the
    rest of the system had travelled days ahead.

    Outside the simulator the offset is zero and this is exactly
    `datetime.now(tz=MX_TZ)`; see app/core/clock.py.

    Returns:
        Current datetime in America/Mexico_City, shifted by the simulated clock
        offset when a simulator run is active.
    """
    return datetime.now(tz=MX_TZ) + clock_offset()


def real_now() -> datetime:
    """The wall clock, ignoring the conversation simulator's offset (UTC).

    Only for expiries owned by an external service — a Google access token,
    a Google watch channel. Those run on real time whatever the simulator says:
    a token refreshed while the simulated clock stood days ahead was stored as
    valid "until next Monday", Google expired it an hour later, and after the
    clock reset the app kept sending it (401) because by its own clock it
    hadn't expired. Everything about the practice's own timeline uses now_mx().
    """
    from datetime import timezone

    return datetime.now(tz=timezone.utc)


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
