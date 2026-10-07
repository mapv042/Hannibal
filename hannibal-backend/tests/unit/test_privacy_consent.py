"""Reading a person's answer to the privacy notice — in code, never by the model.

Consent to process health data has to be explicit and provable, so only a
tapped button or a plain yes/no typed while the question is open counts.
"""

import uuid
from types import SimpleNamespace

from app.modules.privacy import consent


def test_tapped_accept_button_is_consent_with_its_message_id():
    burst = [
        {"type": "text", "id": "m1", "text": {"body": "hola"}},
        {"type": "interactive", "id": "m2",
         "interactive": {"button_reply": {"id": consent.BUTTON_ACCEPT, "title": "Acepto"}}},
    ]
    assert consent.answer_from_messages(burst) == (True, "m2")


def test_tapped_decline_button():
    burst = [{"type": "interactive", "id": "m3",
              "interactive": {"button_reply": {"id": consent.BUTTON_DECLINE, "title": "No acepto"}}}]
    assert consent.answer_from_messages(burst) == (False, "m3")


def test_other_buttons_are_not_consent():
    # The day-before reminder's buttons carry ids like confirm_<appointment>.
    burst = [{"type": "interactive", "id": "m4",
              "interactive": {"button_reply": {"id": "confirm_123", "title": "Sí, confirmo"}}}]
    assert consent.answer_from_messages(burst) is None


def test_typed_answers():
    assert consent.answer_from_text("¡Sí, acepto!") is True
    assert consent.answer_from_text("Acepto") is True
    assert consent.answer_from_text("de acuerdo") is True
    assert consent.answer_from_text("No acepto") is False
    assert consent.answer_from_text("no") is False


def test_a_longer_message_is_not_an_answer():
    # "sí, pero mejor el martes" is about the appointment, not the notice.
    assert consent.answer_from_text("sí, pero mejor el martes") is None
    assert consent.answer_from_text("¿qué datos van a guardar?") is None


def test_question_links_the_office_notice_in_its_register():
    office = SimpleNamespace(id=uuid.uuid4(), name="Consultorio Demo", assistant_tone="formal")
    text = consent.consent_request_text(office)
    assert f"/aviso/{office.id}" in text
    assert "¿Está de acuerdo?" in text and "su cita" in text

    office.assistant_tone = "informal"
    assert "¿Estás de acuerdo?" in consent.consent_request_text(office)
