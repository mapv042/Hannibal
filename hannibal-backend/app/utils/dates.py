from __future__ import annotations

from datetime import date as date_cls, datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from app.core.constants import DAYS_ES, MX_TIMEZONE as MX_TZ

# How many days the reference calendar injected into the LLM prompts spans.
DATE_REFERENCE_DAYS = 30

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
        f"FECHA Y HORA ACTUAL: {today.isoformat()} ({DAYS_ES[today.weekday()]}), {now.strftime('%H:%M')} hrs",
        "ZONA HORARIA: Centro de México (CST)",
        "",
        f"CALENDARIO DE REFERENCIA (próximos {days} días — usa estas fechas tal cual, NO las recalcules):",
    ]
    for i in range(days):
        day = today + timedelta(days=i)
        weekday = DAYS_ES[day.weekday()]
        label = _RELATIVE_LABELS.get(i)
        prefix = f"{label}: " if label else ""
        lines.append(f"- {prefix}{weekday} {day.isoformat()}")
    lines.append("")
    lines.append(
        'Para un día de la semana sin más detalle (ej. "el lunes"), usa su próxima ocurrencia '
        "en la lista. Para fechas más allá del calendario, calcula a partir de HOY. Siempre "
        "verifica la fecha con la herramienta de disponibilidad: te devuelve el día de la semana "
        "real, así confirmas que elegiste el día correcto."
    )
    return "\n".join(lines)


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
    """'mañana (miércoles 17/06/2026)' or 'jueves 18/06/2026' if not hoy/mañana."""
    absolute = f"{DAYS_ES[target_date.weekday()]} {target_date.strftime('%d/%m/%Y')}"
    relative = relative_day_label(target_date, today)
    return f"{relative} ({absolute})" if relative else absolute


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
