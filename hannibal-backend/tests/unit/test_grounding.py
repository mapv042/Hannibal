"""The reply validator: what it must catch, and what it must let through."""

from datetime import date

import pytest

from app.modules.conversation.grounding import (
    Evidence,
    claimed_kinds,
    evidence_minutes,
    validate_reply,
)

TODAY = date(2026, 9, 23)  # a Wednesday


def ev(claims=(), texts=()):
    return Evidence.build(today=TODAY, claims=claims, texts=texts)


def kinds(reply, evidence):
    return {v.kind for v in validate_reply(reply, evidence)}


# --- claimed actions ---------------------------------------------------------

@pytest.mark.parametrize("reply,kind", [
    ("Listo, tu cita quedó agendada para el jueves.", "book"),
    ("Ya te agendé con el doctor.", "book"),
    ("Tu cita fue cancelada.", "cancel"),
    ("Cancelé tu cita del jueves.", "cancel"),
    ("Tu cita quedó reagendada al viernes.", "reschedule"),
    ("Ya le avisé al doctor de tu urgencia.", "notify_doctor"),
    ("Tu asistencia quedó confirmada.", "confirm_attendance"),
    ("Mensaje enviado a Juan.", "message_sent"),
])
def test_detects_completed_action_claims(reply, kind):
    assert kind in claimed_kinds(reply)


@pytest.mark.parametrize("reply", [
    "¿Quieres que te agende el jueves?",
    "¿Te cancelo la cita?",
    "No quedó agendada todavía: necesito que me confirmes.",
    "Aún no he cancelado nada.",
    "Puedo agendarte, cancelar o reagendar tu cita.",
    "Cuando confirmes, la agendo.",
])
def test_ignores_offers_questions_and_negations(reply):
    assert claimed_kinds(reply) == set()


def test_claim_without_backing_is_a_violation():
    assert "claimed_action" in kinds("Listo, tu cita quedó agendada.", ev())


def test_claim_backed_by_a_tool_passes():
    assert "claimed_action" not in kinds("Listo, tu cita quedó agendada.", ev(claims={"book"}))


def test_backing_is_per_kind():
    # A booking doesn't back saying the doctor was notified.
    assert "claimed_action" in kinds("Te agendé y ya le avisé al doctor.", ev(claims={"book"}))


# --- times -------------------------------------------------------------------

def test_time_from_tools_passes():
    e = ev(texts=['{"slot_id": "2026-09-24T16:00", "label": "4:00 PM"}'])
    assert "unsupported_time" not in kinds("Tengo el jueves a las 4:00 PM.", e)


def test_invented_time_is_flagged():
    e = ev(texts=['{"slot_id": "2026-09-24T16:00", "label": "4:00 PM"}'])
    assert "unsupported_time" in kinds("Tengo a las 4:00 PM y a las 11:30 AM.", e)


def test_wrong_half_of_day_is_flagged():
    # The classic: the patient asked for 4 PM, the reply says 4 AM.
    e = ev(texts=['{"slot_id": "2026-09-24T16:00"}'])
    assert "unsupported_time" in kinds("Quedó a las 4:00 AM.", e)


def test_users_own_time_counts_as_evidence():
    e = ev(texts=["¿tienes a las 5?"])
    assert "unsupported_time" not in kinds("A las 5:00 PM no tengo espacio.", e)


def test_durations_are_not_times():
    assert kinds("Te recordaremos 24 horas antes y 2 horas antes.", ev()) == set()


def test_evidence_minutes_reads_slot_ids_and_labels():
    minutes = evidence_minutes('"2026-09-24T09:30" y "4:00 PM"')
    assert 9 * 60 + 30 in minutes and 16 * 60 in minutes


# --- weekday / date ----------------------------------------------------------

def test_correct_weekday_passes():
    assert "weekday_mismatch" not in kinds("El jueves 24 de septiembre.", ev())


def test_wrong_weekday_is_flagged():
    assert "weekday_mismatch" in kinds("El viernes 24 de septiembre.", ev())


def test_wrong_weekday_numeric_date_is_flagged():
    assert "weekday_mismatch" in kinds("lunes 29/09/2026", ev())


def test_weekday_without_month_uses_nearby_months():
    # "martes 29" is true this month (29 Sept 2026 is a Tuesday).
    assert "weekday_mismatch" not in kinds("¿Te queda el martes 29?", ev())


def test_empty_reply_has_no_violations():
    assert validate_reply("", ev()) == []


@pytest.mark.parametrize("reply", [
    "El viernes 10:00 AM está libre.",
    "Para el jueves 11 AM tengo espacio.",
    "— María García → jueves 10:00 AM ✓",
])
def test_weekday_followed_by_a_time_is_not_a_date(reply):
    e = ev(texts=["10:00 AM 11:00 AM"])
    assert "weekday_mismatch" not in kinds(reply, e)
