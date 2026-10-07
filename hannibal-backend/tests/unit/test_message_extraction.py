"""Turning raw webhook messages into the text the model reads."""

from app.modules.conversation.manager import ConversationManager


def _manager() -> ConversationManager:
    return ConversationManager(session_store=None, meta_client=None, ai_service=object())


async def test_template_quick_reply_tap_reads_as_its_title():
    # Tapping a template button (the day-before confirmation's Reagendar)
    # arrives as type "button", not "interactive".
    message = {
        "from": "5215512345678",
        "id": "wamid.1",
        "type": "button",
        "button": {"payload": "Reagendar", "text": "Reagendar"},
    }
    extracted = await _manager().extract_message(message, office=None)
    assert extracted == {"from": "5215512345678", "text": "Reagendar", "id": "wamid.1"}


async def test_interactive_button_reply_reads_as_its_title():
    message = {
        "from": "5215512345678",
        "id": "wamid.2",
        "type": "interactive",
        "interactive": {"button_reply": {"id": "confirm_123", "title": "Confirmar"}},
    }
    extracted = await _manager().extract_message(message, office=None)
    assert extracted["text"] == "Confirmar"
