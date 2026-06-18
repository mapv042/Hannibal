"""Shared helper to send a window-aware WhatsApp alert to the doctor (office owner).

Centralizes the pattern already used by the urgency and reschedule notifications:
validate the office WhatsApp config, then send free text while the doctor's 24h
service window is open, or fall back to an approved Meta template otherwise.

The existing urgency/reschedule flows keep their own inline implementation (they
must stay unchanged); new doctor notifications should use this helper instead of
duplicating the logic.
"""

from __future__ import annotations

from typing import Dict, List, Optional

import redis.asyncio as aioredis

from app.db.models import Office
from app.modules.reminders.wa_templates import TEMPLATE_LANGUAGE
from app.modules.whatsapp.window import doctor_service_window_open
from app.utils.logger import get_logger

logger = get_logger(__name__)


async def send_doctor_alert(
    redis_client: aioredis.Redis,
    meta_client,
    office: Office,
    *,
    text: str,
    template_name: str,
    template_params: List[Dict[str, str]],
    log_event: str = "doctor_alert",
) -> str:
    """Send a doctor alert: free text in-window, approved template otherwise.

    Returns "notified" if a message was sent, or "skipped" when the office is
    missing WhatsApp config or the send fails. Loading the entity and deciding
    whether the notification is enabled is the caller's responsibility.
    """
    if not (office.owner_phone and office.whatsapp_phone_id and office.whatsapp_token):
        logger.warning(f"{log_event}_missing_config", office_id=str(office.id))
        return "skipped"

    try:
        if await doctor_service_window_open(redis_client, office.id):
            await meta_client.send_text_message(
                phone_number_id=office.whatsapp_phone_id,
                token=office.whatsapp_token,
                to=office.owner_phone,
                text=text,
            )
            via = "text"
        else:
            await meta_client.send_template_message(
                phone_number_id=office.whatsapp_phone_id,
                token=office.whatsapp_token,
                to=office.owner_phone,
                template_name=template_name,
                params=template_params,
                language_code=TEMPLATE_LANGUAGE,
            )
            via = "template"
    except Exception as e:
        logger.error(f"{log_event}_failed", office_id=str(office.id), error=str(e), exc_info=True)
        return "skipped"

    logger.info(f"{log_event}_notified", office_id=str(office.id), via=via)
    return "notified"
