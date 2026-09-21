"""Which WhatsApp client the app sends through.

Everything that sends a WhatsApp message asks for a client here rather than
constructing `MetaCloudClient()` directly. That one seam is what lets the
conversation simulator run the whole system against a recorded outbox instead of
Meta, without the managers, tools, reminders or notifications knowing.

Safety, in order of how much it is relied on:

1. **The factory refuses to fake in production.** `WHATSAPP_TRANSPORT=fake` with
   `ENVIRONMENT=production` is a misconfiguration, not a request, and is ignored.
2. **The simulator's office carries invalid Meta credentials.** The real client
   takes `phone_number_id` and `token` per call from the office row, so even a
   real client in a simulator environment would get a 401 from Meta rather than
   message a live person. That is the layer that does not depend on anyone
   configuring anything correctly, and it is why the seed writes junk there.

Both matter because the flag has to be shared by the API *and* the worker: the
reminders all go out from the worker, so a fake transport that reached only the
API would still message real people.
"""

from __future__ import annotations

from typing import Union

from app.config import settings
from app.modules.whatsapp.fake_client import FakeMetaClient
from app.modules.whatsapp.meta_client import MetaCloudClient
from app.utils.logger import get_logger

logger = get_logger(__name__)

WhatsAppClient = Union[MetaCloudClient, FakeMetaClient]


def use_fake_transport() -> bool:
    """Whether outbound WhatsApp should be recorded instead of sent."""
    if settings.whatsapp_transport.lower() != "fake":
        return False

    if settings.is_production:
        logger.error(
            "fake_whatsapp_transport_refused",
            detail="WHATSAPP_TRANSPORT=fake ignored because ENVIRONMENT=production",
        )
        return False

    return True


def get_meta_client(timeout: int = 30) -> WhatsAppClient:
    """Return the WhatsApp client this environment should send through.

    Args:
        timeout: HTTP timeout in seconds, passed through to the real client.

    Returns:
        A `FakeMetaClient` when the fake transport is active, else a
        `MetaCloudClient`. Both expose the same methods.
    """
    if use_fake_transport():
        return FakeMetaClient(timeout=timeout)

    return MetaCloudClient(timeout=timeout)
