"""A stand-in for MetaCloudClient that writes to Redis instead of to Meta.

The conversation simulator runs the real system — real managers, real tools, real
booking, real Google Calendar — and swaps only the edges. This is the outbound
edge: same interface as `MetaCloudClient`, but every message lands in a Redis
list the simulator UI reads, so a scenario can be played out without a phone
number, without Meta, and without messaging a real person.

Two things it deliberately preserves:

- **The 24h-window distinction.** Free text and interactive buttons are recorded
  as separate kinds from templates, because outside the window only templates go
  out and getting that wrong is one of the bugs worth catching. The recorded
  template name and params are also how a template can be reviewed before it is
  ever submitted to Meta for approval.
- **Who each message went to.** The simulator routes a message to the patient or
  the doctor panel purely by its `to` number, the same way production decides
  who to notify, so no extra plumbing is needed to tell the two apart.

Media is not carried: the simulator sends text and button taps, so the media
methods raise rather than pretend. A voice note in a scenario is a real gap, and
a loud failure is the honest way to say so.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional
from uuid import uuid4

import redis.asyncio as aioredis

from app.config import settings
from app.core.exceptions import WhatsAppError
from app.utils.dates import now_mx
from app.utils.logger import get_logger

logger = get_logger(__name__)

# One list per sending number; the simulator reads and clears it.
OUTBOX_KEY = "sim:outbox:{phone_number_id}"

# Long enough to outlive any session, short enough to not accumulate forever.
OUTBOX_TTL_SECONDS = 24 * 60 * 60

# Keeps a runaway scenario from growing the list without bound.
OUTBOX_MAX_MESSAGES = 2000


class FakeMetaClient:
    """Records outbound WhatsApp messages in Redis. Same surface as MetaCloudClient."""

    def __init__(self, timeout: int = 30):
        """Accepts MetaCloudClient's signature so the two are interchangeable."""
        self.timeout = timeout

    async def _record(
        self,
        phone_number_id: str,
        to: str,
        kind: str,
        **payload: Any,
    ) -> str:
        """Append one outbound message to the office's outbox and return its id.

        The timestamp is the **simulated** clock, not the wall clock, so the
        transcript reads as the timeline the scenario is exercising.
        """
        message_id = f"wamid.sim.{uuid4().hex}"
        entry = {
            "message_id": message_id,
            "to": to,
            "kind": kind,
            "sent_at": now_mx().isoformat(),
            **payload,
        }

        key = OUTBOX_KEY.format(phone_number_id=phone_number_id)
        client = aioredis.from_url(settings.redis_url, decode_responses=True)
        try:
            pipe = client.pipeline()
            pipe.rpush(key, json.dumps(entry, ensure_ascii=False))
            pipe.ltrim(key, -OUTBOX_MAX_MESSAGES, -1)
            pipe.expire(key, OUTBOX_TTL_SECONDS)
            await pipe.execute()
        finally:
            await client.aclose()

        logger.info(
            "sim_outbound_recorded",
            to=to,
            kind=kind,
            message_id=message_id,
        )
        return message_id

    async def send_text_message(
        self,
        phone_number_id: str,
        token: str,
        to: str,
        text: str,
    ) -> str:
        """Record a free-text message (only valid inside the 24h window)."""
        return await self._record(phone_number_id, to, "text", body=text)

    async def send_template_message(
        self,
        phone_number_id: str,
        token: str,
        to: str,
        template_name: str,
        params: Optional[List[Dict[str, str]]] = None,
        language_code: str = "es",
    ) -> str:
        """Record a template send, keeping the name and params for review."""
        return await self._record(
            phone_number_id,
            to,
            "template",
            template_name=template_name,
            params=params or [],
            language_code=language_code,
        )

    async def send_interactive_buttons(
        self,
        phone_number_id: str,
        token: str,
        to: str,
        body_text: str,
        buttons: List[Dict[str, str]],
    ) -> str:
        """Record a buttons message so the UI can render them as real buttons.

        A tap comes back in as the button's *title* text, which is what production
        does too — the id is dropped on the way in.
        """
        return await self._record(
            phone_number_id,
            to,
            "interactive",
            body=body_text,
            buttons=buttons,
        )

    async def mark_as_read(
        self,
        phone_number_id: str,
        token: str,
        message_id: str,
    ) -> bool:
        """No-op: nothing is delivered, so read receipts mean nothing here."""
        return True

    async def get_media_url(
        self,
        phone_number_id: str,
        token: str,
        media_id: str,
    ) -> str:
        raise WhatsAppError("the simulator carries no media (voice notes, images)")

    async def download_media(
        self,
        media_url: str,
        token: str,
    ) -> bytes:
        raise WhatsAppError("the simulator carries no media (voice notes, images)")

    async def upload_media(
        self,
        phone_number_id: str,
        token: str,
        file_content: bytes,
        file_type: str,
        filename: Optional[str] = None,
    ) -> str:
        raise WhatsAppError("the simulator carries no media (voice notes, images)")
