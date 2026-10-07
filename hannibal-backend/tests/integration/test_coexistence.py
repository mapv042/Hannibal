"""The doctor answers one patient from the WhatsApp Business app (coexistence).

Before, the bot kept answering that patient alongside the doctor — or the
doctor had to pause it for everyone. Now an `smb_message_echoes` webhook puts
only that thread on hold, and the doctor's words join the patient's history.

DESTRUCTIVE like test_patient_booking_flow: RUN_INTEGRATION=1 and a local DB.
"""

from __future__ import annotations

import os
import uuid

import pytest
import redis.asyncio as aioredis
from sqlalchemy import select

from app.config import settings

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_INTEGRATION") != "1"
    or not any(h in settings.database_url for h in ("localhost", "127.0.0.1")),
    reason="destructive: needs RUN_INTEGRATION=1 and a local DATABASE_URL",
)

from app.db.base import dispose_engine, get_async_session_maker  # noqa: E402
from app.db.models import Conversation, Message  # noqa: E402
from app.modules.conversation.session_store import SessionStore  # noqa: E402
from app.modules.sim import seed as sim_seed  # noqa: E402
from app.modules.whatsapp import router as wa_router  # noqa: E402
from app.modules.whatsapp.coexistence import conversation_taken_until  # noqa: E402

PATIENT = sim_seed.DEFAULT_PATIENT_PHONE
OTHER = "5215550000088"


def _payload(office, *, messages=None, echoes=None):
    value = {"messaging_product": "whatsapp", "metadata": {"phone_number_id": office.whatsapp_phone_id}}
    if messages is not None:
        value["messages"] = messages
    if echoes is not None:
        value["message_echoes"] = echoes
    return {"object": "whatsapp_business_account", "entry": [{"changes": [{"value": value}]}]}


def _text(sender, body):
    return {"from": sender, "id": f"wamid.in.{uuid.uuid4().hex}", "type": "text", "text": {"body": body}}


@pytest.fixture
async def env(monkeypatch):
    redis_client = aioredis.from_url(settings.redis_url, decode_responses=True)
    async with get_async_session_maker()() as db:
        office = await sim_seed.reset(db)
    for number in (PATIENT, OTHER):
        await redis_client.delete(f"session:{number}:{office.id}")
        await redis_client.delete(f"conv_takeover:{office.id}:{number}")
    monkeypatch.setattr(settings, "message_coalesce_seconds", 0)

    answered: list[str] = []

    async def fake_process(self, office, messages, db):
        answered.append(messages[0]["from"])

    monkeypatch.setattr(wa_router.ConversationManager, "process", fake_process)
    yield office, redis_client, answered
    await redis_client.aclose()
    await dispose_engine()


async def test_doctor_echo_holds_only_that_thread(env):
    office, redis_client, answered = env

    echo = {
        "from": office.whatsapp_phone, "to": PATIENT, "id": f"wamid.echo.{uuid.uuid4().hex}",
        "timestamp": "1790000000", "type": "text",
        "text": {"body": "Hola Juan, soy la doctora. Trae tus estudios el martes."},
    }
    await wa_router._process_webhook_async(_payload(office, echoes=[echo]), redis_client)

    assert await conversation_taken_until(office.id, PATIENT, redis_client) is not None
    session = await SessionStore(redis_client).get_session(PATIENT, str(office.id))
    assert session.claude_history[-1]["content"].startswith("Hola Juan, soy la doctora")

    # Juan answers: kept, not answered. Another patient: answered as usual.
    await wa_router._process_webhook_async(
        _payload(office, messages=[_text(PATIENT, "Va, gracias doctora")]), redis_client
    )
    await wa_router._process_webhook_async(
        _payload(office, messages=[_text(OTHER, "Hola, quiero una cita")]), redis_client
    )
    assert answered == [OTHER]

    async with get_async_session_maker()() as db:
        rows = (await db.execute(
            select(Message.direction, Message.content, Message.extra_metadata)
            .join(Conversation, Message.conversation_id == Conversation.id)
            .where(Conversation.whatsapp_id == PATIENT)
            .order_by(Message.created_at)
        )).all()
    assert [(d, c) for d, c, _ in rows] == [
        ("outgoing", "Hola Juan, soy la doctora. Trae tus estudios el martes."),
        ("incoming", "Va, gracias doctora"),
    ]
    assert rows[0].extra_metadata["source"] == "doctor_app"


async def test_the_same_echo_twice_is_recorded_once(env):
    office, redis_client, _ = env
    echo = {"from": office.whatsapp_phone, "to": PATIENT, "id": "wamid.echo.dup",
            "type": "text", "text": {"body": "Nos vemos mañana"}}
    await redis_client.delete("wamsg_dedup:wamid.echo.dup")
    for _ in range(2):
        await wa_router._process_webhook_async(_payload(office, echoes=[echo]), redis_client)

    async with get_async_session_maker()() as db:
        count = len((await db.execute(
            select(Message).where(Message.whatsapp_message_id == "wamid.echo.dup")
        )).scalars().all())
    assert count == 1
