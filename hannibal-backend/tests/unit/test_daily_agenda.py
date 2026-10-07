"""The doctor's morning summary: the day at a glance, before the first cita."""

from app.modules.notifications.templates import (
    agenda_line,
    daily_agenda_detail,
    doctor_daily_agenda,
)


def test_line_marks_first_visits_and_unconfirmed():
    assert agenda_line("9:00 AM", "María García", first_visit=True, unconfirmed=True) == (
        "9:00 AM — María García (primera vez) · sin confirmar"
    )
    assert agenda_line("10:00 AM", "Juan Pérez", first_visit=False, unconfirmed=False) == (
        "10:00 AM — Juan Pérez"
    )


def test_summary_lists_citas_urgencies_and_free_slots():
    text = doctor_daily_agenda(
        ["9:00 AM — María García", "10:00 AM — Juan Pérez · sin confirmar"],
        pending_urgencies=1,
        free_slots=3,
    )
    assert text.startswith("Buen día. Tu agenda de hoy (2 citas):")
    assert "• 10:00 AM — Juan Pérez · sin confirmar" in text
    assert "1 solicitud urgente esperando tu respuesta" in text
    assert "Quedan 3 horarios libres hoy." in text


def test_summary_register_and_empty_day():
    text = doctor_daily_agenda([], pending_urgencies=2, free_slots=None, tone="formal")
    assert "Hoy no tienes citas agendadas." in text
    assert "2 solicitudes urgentes" in text
    assert "dígamelo" in text
    assert "horario" not in text  # unknown free slots are not guessed


def test_template_detail_is_one_bounded_line():
    lines = [f"{h}:00 AM — Paciente {h}" for h in range(1, 200)]
    detail = daily_agenda_detail(lines)
    assert "\n" not in detail and len(detail) <= 700
