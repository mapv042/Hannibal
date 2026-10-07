"""The conversations view tells the doctor who wrote each outgoing message.

Every outgoing row is "sent by the office", but the doctor reading a thread
needs to tell the assistant's words from their own approved messages and from
the fixed reminder texts — that is what the metadata each writer leaves is for.
"""

import uuid

from app.db.models import Message
from app.modules.conversation.inbox import message_author


def _msg(direction: str, metadata: dict | None = None) -> Message:
    return Message(
        id=uuid.uuid4(),
        conversation_id=uuid.uuid4(),
        content="hola",
        type="text",
        direction=direction,
        extra_metadata=metadata,
    )


def test_incoming_is_the_patient():
    assert message_author(_msg("incoming")) == "patient"


def test_plain_outgoing_is_the_assistant():
    assert message_author(_msg("outgoing")) == "assistant"


def test_doctor_approved_message():
    assert message_author(_msg("outgoing", {"source": "doctor_send_message"})) == "doctor"


def test_reminder_task_message():
    assert message_author(_msg("outgoing", {"source": "reminder_task", "via": "template"})) == "reminder"
