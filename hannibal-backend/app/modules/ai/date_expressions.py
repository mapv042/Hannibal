"""Resolve the way a patient names a day ("el miércoles", "el próximo martes",
"mañana en la tarde", "el 5") into exact dates — in code, not in the model.

Why this exists: the model did date arithmetic itself, from a reference
calendar in the prompt, and got it wrong a small but steady fraction of the
time. The eval that caught it: on a Monday, "el miércoles en la mañana" was
booked for the Wednesday of the FOLLOWING week, although the prompt said "use
the next occurrence". A rule in the prompt is a suggestion; this module is the
rule. The model passes the patient's words (get_available_slots `when`), and
gets back exact dates — or, when the words genuinely have two readings, both
options so it can ask.

Conventions (Mexican Spanish):
- A bare weekday ("el miércoles") is its next occurrence. Said on that same
  weekday ("el lunes", on a Monday) it's ambiguous: today, or in a week.
- "este miércoles" is the next occurrence, today included.
- "el próximo / siguiente miércoles", "el miércoles que viene": the next
  occurrence when that is already in next week; when it still falls in the
  current week, people split between the two readings, so it's ambiguous.
- "el miércoles de la otra / próxima / siguiente semana", "... de la semana que
  entra": that weekday in next week (Monday-based weeks).
- "el 5" is the next 5th (this month if it hasn't passed, else next month).
- "5 de octubre", "5/10", "5/10/2026" are day-first; a month without a year is
  the next one to come.
- "en la mañana" is before 12:00, "en la tarde" from 12:00 — the same cut as
  get_available_slots' part_of_day.

Anything it can't read returns None: the tool then tells the model to ask the
patient, never to guess.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional

_WEEKDAYS = {
    "lunes": 0, "martes": 1, "miercoles": 2, "jueves": 3,
    "viernes": 4, "sabado": 5, "domingo": 6,
}
_MONTHS = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
    "julio": 7, "agosto": 8, "septiembre": 9, "setiembre": 9, "octubre": 10,
    "noviembre": 11, "diciembre": 12,
}
_NUMBER_WORDS = {
    "un": 1, "una": 1, "uno": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5,
    "seis": 6, "siete": 7, "ocho": 8, "nueve": 9, "diez": 10, "quince": 15,
}

_WD = "(" + "|".join(_WEEKDAYS) + ")"
_MONTH = "(" + "|".join(_MONTHS) + ")"
# With a weekday, any mention of next week anchors it there: "el martes de la
# otra semana", "la próxima semana el martes", "el martes de la semana que entra".
_NEXT_WEEK = r"\b(?:proxima|siguiente|otra) semana\b|\bsemana que (?:entra|viene)\b"

_MORNING_RE = re.compile(r"\b(?:en|por|x|de) la manana\b|\btemprano\b|\bantes de (?:las )?12\b")
_AFTERNOON_RE = re.compile(r"\b(?:en|por|x|de) la tarde\b|\bdespues de comer\b|\bmedio ?dia\b")


@dataclass
class DayResolution:
    """What a day expression means.

    `dates` holds one date, or several for a span ("la otra semana"). When
    `ambiguous` is set, `dates` are the alternative readings — the caller must
    ask, not pick.
    """

    dates: list[date]
    ambiguous: bool = False
    part_of_day: Optional[str] = None
    note: Optional[str] = None
    alternatives: list[date] = field(default_factory=list)


def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFD", text.lower())
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    text = re.sub(r"[¿?¡!,.;:]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _next_weekday(today: date, weekday: int, include_today: bool) -> date:
    delta = (weekday - today.weekday()) % 7
    if delta == 0 and not include_today:
        delta = 7
    return today + timedelta(days=delta)


def _monday_of_next_week(today: date) -> date:
    return today - timedelta(days=today.weekday()) + timedelta(days=7)


def _same_week(a: date, b: date) -> bool:
    return a.isocalendar()[:2] == b.isocalendar()[:2]


def _day_of_month(today: date, day: int) -> Optional[date]:
    """The next date whose day-of-month is `day` (this month, else following)."""
    for months_ahead in range(0, 3):
        month_index = today.month - 1 + months_ahead
        year, month = today.year + month_index // 12, month_index % 12 + 1
        try:
            candidate = date(year, month, day)
        except ValueError:
            continue
        if candidate >= today:
            return candidate
    return None


def _day_and_month(today: date, day: int, month: int, year: Optional[int]) -> Optional[date]:
    if year is not None:
        if year < 100:
            year += 2000
        try:
            return date(year, month, day)
        except ValueError:
            return None
    for y in (today.year, today.year + 1):
        try:
            candidate = date(y, month, day)
        except ValueError:
            continue
        if candidate >= today:
            return candidate
    return None


def _part_of_day(text: str) -> tuple[Optional[str], str]:
    """Detect mañana/tarde, and strip those phrases so "mañana en la mañana"
    leaves just the day word."""
    part = None
    if _MORNING_RE.search(text):
        part = "mañana"
        text = _MORNING_RE.sub(" ", text)
    elif _AFTERNOON_RE.search(text):
        part = "tarde"
        text = _AFTERNOON_RE.sub(" ", text)
    return part, re.sub(r"\s+", " ", text).strip()


def resolve_day_expression(expression: str, today: date) -> Optional[DayResolution]:
    """Read a Spanish day expression relative to `today`. None if unreadable."""
    if not expression or not expression.strip():
        return None
    part, t = _part_of_day(_normalize(expression))

    def done(dates, **kw) -> DayResolution:
        return DayResolution(dates=dates, part_of_day=part, **kw)

    # --- explicit dates ----------------------------------------------------
    m = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", t)
    if m:
        try:
            return done([date(int(m.group(1)), int(m.group(2)), int(m.group(3)))])
        except ValueError:
            return None

    m = re.search(r"\b(\d{1,2})\s*/\s*(\d{1,2})(?:\s*/\s*(\d{2,4}))?\b", t)
    if m:
        d = _day_and_month(today, int(m.group(1)), int(m.group(2)),
                           int(m.group(3)) if m.group(3) else None)
        return done([d]) if d else None

    m = re.search(r"\b(\d{1,2}) de " + _MONTH + r"(?: (?:de )?(\d{4}))?\b", t)
    if m:
        d = _day_and_month(today, int(m.group(1)), _MONTHS[m.group(2)],
                           int(m.group(3)) if m.group(3) else None)
        if d is None:
            return None
        wd = re.search(r"\b" + _WD + r"\b", t)
        if wd and _WEEKDAYS[wd.group(1)] != d.weekday():
            return _weekday_number_conflict(t, today, d, _WEEKDAYS[wd.group(1)], part)
        return done([d])

    # --- relative words ----------------------------------------------------
    if re.search(r"\bpasado manana\b", t):
        return done([today + timedelta(days=2)])
    if re.search(r"\bmanana\b", t):
        return done([today + timedelta(days=1)])
    if re.search(r"\bhoy\b", t):
        return done([today])

    m = re.search(r"\b(?:en|dentro de) (\d{1,2}|" + "|".join(_NUMBER_WORDS) + r") (dias?|semanas?)\b", t)
    if m:
        n = int(m.group(1)) if m.group(1).isdigit() else _NUMBER_WORDS[m.group(1)]
        days = n * 7 if m.group(2).startswith("semana") else n
        return done([today + timedelta(days=days)])

    if re.search(r"\bfin de semana\b", t):
        sat = _next_weekday(today, 5, include_today=True)
        if today.weekday() == 6:
            return done([today])
        next_week = re.search(r"\b(?:proximo|siguiente|otro) fin de semana\b", t)
        if next_week and _same_week(sat, today):
            sat += timedelta(days=7)
        return done([sat, sat + timedelta(days=1)])

    # --- weekdays ----------------------------------------------------------
    wd_match = re.search(r"\b" + _WD + r"\b", t)
    if wd_match:
        weekday = _WEEKDAYS[wd_match.group(1)]

        # "el miércoles 30": the number decides, the weekday must agree.
        num = re.search(r"\b" + _WD + r" (\d{1,2})\b", t)
        if num:
            d = _day_of_month(today, int(num.group(2)))
            if d is not None:
                if d.weekday() == weekday:
                    return done([d])
                return _weekday_number_conflict(t, today, d, weekday, part)

        if re.search(_NEXT_WEEK, t):
            return done([_monday_of_next_week(today) + timedelta(days=weekday)])

        if re.search(r"\b(?:este|esta)\s+" + _WD, t):
            return done([_next_weekday(today, weekday, include_today=True)])

        if re.search(r"\b(?:proximo|siguiente)\s+" + _WD + r"|" + _WD + r" (?:que viene|que entra)\b", t):
            occurrence = _next_weekday(today, weekday, include_today=False)
            if _same_week(occurrence, today):
                return done(
                    [occurrence, occurrence + timedelta(days=7)],
                    ambiguous=True,
                    note="«el próximo» puede ser el de esta semana o el de la siguiente",
                )
            return done([occurrence])

        if weekday == today.weekday():
            return done(
                [today, today + timedelta(days=7)],
                ambiguous=True,
                note="hoy es ese mismo día de la semana",
            )
        return done([_next_weekday(today, weekday, include_today=False)])

    # --- week spans --------------------------------------------------------
    if re.search(r"\b(?:proxima|siguiente|otra) semana\b|\bsemana que (?:entra|viene)\b", t):
        monday = _monday_of_next_week(today)
        return done([monday + timedelta(days=i) for i in range(7)])
    if re.search(r"\besta semana\b", t):
        return done([today + timedelta(days=i) for i in range(7 - today.weekday())])

    # --- a bare day number: "el 5", "el día 5" -----------------------------
    m = re.search(r"^(?:el )?(?:dia )?(\d{1,2})$", t) or re.search(r"\b(?:el|dia) (\d{1,2})\b", t)
    if m and 1 <= int(m.group(1)) <= 31:
        d = _day_of_month(today, int(m.group(1)))
        return done([d]) if d else None

    return None


def _weekday_number_conflict(t, today, by_number: date, weekday: int, part) -> DayResolution:
    by_weekday = _next_weekday(today, weekday, include_today=True)
    names = {v: k for k, v in _WEEKDAYS.items()}
    return DayResolution(
        dates=sorted({by_number, by_weekday}),
        ambiguous=True,
        part_of_day=part,
        note=(
            f"el día {by_number.day} no cae en {names[weekday].replace('miercoles', 'miércoles').replace('sabado', 'sábado')}"
        ),
    )
