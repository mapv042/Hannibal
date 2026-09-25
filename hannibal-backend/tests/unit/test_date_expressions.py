"""Spanish day expressions → exact dates (the model no longer does this)."""

from datetime import date

import pytest

from app.modules.ai.date_expressions import resolve_day_expression as resolve

MON = date(2026, 9, 28)   # Monday
WED = date(2026, 9, 30)   # Wednesday
FRI = date(2026, 10, 2)   # Friday


def one(expr, today=MON):
    r = resolve(expr, today)
    assert r is not None and not r.ambiguous and len(r.dates) == 1, (expr, r)
    return r.dates[0]


def options(expr, today=MON):
    r = resolve(expr, today)
    assert r is not None and r.ambiguous, (expr, r)
    return r.dates


# --- the eval failure that motivated this --------------------------------------

def test_bare_weekday_is_its_next_occurrence():
    assert one("el miércoles en la mañana") == date(2026, 9, 30)  # not Oct 7
    assert one("miercoles") == date(2026, 9, 30)
    assert one("el viernes", today=WED) == FRI


def test_weekday_said_on_that_weekday_is_ambiguous():
    assert options("el lunes") == [MON, date(2026, 10, 5)]


def test_este_includes_today():
    assert one("este lunes") == MON
    assert one("este jueves") == date(2026, 10, 1)


def test_proximo_within_this_week_is_ambiguous():
    assert options("el próximo miércoles") == [date(2026, 9, 30), date(2026, 10, 7)]
    assert options("el miércoles que viene") == [date(2026, 9, 30), date(2026, 10, 7)]


def test_proximo_already_next_week_is_unambiguous():
    # On Friday, the next Tuesday is already in next week.
    assert one("el próximo martes", today=FRI) == date(2026, 10, 6)


@pytest.mark.parametrize("expr", [
    "el miércoles de la otra semana",
    "el miercoles de la proxima semana",
    "la próxima semana el miércoles",
    "el miércoles de la semana que entra",
])
def test_weekday_of_next_week(expr):
    assert one(expr) == date(2026, 10, 7)


# --- relative words -----------------------------------------------------------

def test_relative_words():
    assert one("hoy") == MON
    assert one("mañana") == date(2026, 9, 29)
    assert one("pasado mañana") == date(2026, 9, 30)
    assert one("en 3 días") == date(2026, 10, 1)
    assert one("dentro de una semana") == date(2026, 10, 5)


def test_manana_as_day_and_as_part_of_day():
    r = resolve("mañana en la mañana", MON)
    assert r.dates == [date(2026, 9, 29)] and r.part_of_day == "mañana"
    r = resolve("pa mañana x la tarde", MON)
    assert r.dates == [date(2026, 9, 29)] and r.part_of_day == "tarde"
    assert resolve("el jueves en la mañana", MON).dates == [date(2026, 10, 1)]


def test_part_of_day_alone_has_no_date():
    assert resolve("en la tarde", MON) is None


# --- numbers and months ------------------------------------------------------

def test_bare_day_number():
    assert one("el 5") == date(2026, 10, 5)      # the 28th has passed: next month
    assert one("el día 30") == date(2026, 9, 30)
    assert one("el 31", today=date(2026, 9, 28)) == date(2026, 10, 31)  # Sept has no 31st


def test_day_and_month():
    assert one("5 de octubre") == date(2026, 10, 5)
    assert one("el 3 de enero") == date(2027, 1, 3)    # next one to come
    assert one("5/10") == date(2026, 10, 5)             # day-first
    assert one("05/10/2026") == date(2026, 10, 5)
    assert one("2026-10-05") == date(2026, 10, 5)


def test_weekday_and_number_agree():
    assert one("el miércoles 30") == date(2026, 9, 30)
    assert one("jueves 1 de octubre") == date(2026, 10, 1)


def test_weekday_and_number_disagree_is_ambiguous():
    r = resolve("el miércoles 1", MON)   # Oct 1 is a Thursday
    assert r.ambiguous and date(2026, 10, 1) in r.dates and date(2026, 9, 30) in r.dates


# --- spans --------------------------------------------------------------------

def test_spans():
    assert resolve("la otra semana", MON).dates[0] == date(2026, 10, 5)
    assert len(resolve("la semana que entra", MON).dates) == 7
    assert resolve("esta semana", WED).dates == [WED + __import__("datetime").timedelta(days=i) for i in range(5)]
    assert resolve("el fin de semana", MON).dates == [date(2026, 10, 3), date(2026, 10, 4)]


@pytest.mark.parametrize("expr", ["", "cuando pueda", "lo antes posible", "asdf"])
def test_unreadable_returns_none(expr):
    assert resolve(expr, MON) is None
