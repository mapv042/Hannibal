"""Consent to the office's privacy notice (LFPDPPP), asked over WhatsApp.

Health data — the reason for a consultation, the intake answers — is
"sensitive personal data" under Mexican law: processing it needs the person's
express consent, and the office must be able to show it. So before the
assistant books (the moment it starts storing that data), the person accepts
the office's notice with a button, and the answer is kept as evidence in
`privacy_consents`.

Everything here is code, not model behaviour: the question is a fixed text,
the answer is read from the button id (or an explicit "sí/acepto" while the
question is pending), and `prepare_booking` refuses until it is recorded.
Answering general questions (hours, prices, location) needs no consent.
"""

from __future__ import annotations

import uuid
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.models import Office, PrivacyConsent
from app.utils.dates import now_mx
from app.utils.logger import get_logger
from app.utils.text import plain_yes_no

logger = get_logger(__name__)

# Bump when the notice text changes materially: everyone is asked again.
PRIVACY_NOTICE_VERSION = "2026-10"

# Session status while the consent question is waiting for an answer.
WAITING_PRIVACY_CONSENT = "waiting_privacy_consent"

BUTTON_ACCEPT = "privacy_accept"
BUTTON_DECLINE = "privacy_decline"

# What the model reads in place of / after the patient's answer, so it knows
# the question was settled without having to interpret a button title.
ACCEPTED_MARKER = "[El paciente aceptó el aviso de privacidad]"
DECLINED_MARKER = "[El paciente no aceptó el aviso de privacidad]"



def notice_url(office: Office) -> str:
    """Public page with this office's privacy notice."""
    return f"{settings.frontend_url.rstrip('/')}/aviso/{office.id}"


def consent_request_text(office: Office) -> str:
    """The fixed consent question, in the office's register (usted / tú)."""
    if office.assistant_tone == "formal":
        your, can, agree = "su", "Puede", "¿Está de acuerdo?"
    else:
        your, can, agree = "tu", "Puedes", "¿Estás de acuerdo?"
    return (
        f"Para agendar {your} cita en {office.name} necesitamos tratar algunos datos "
        f"personales y de salud, como el motivo de consulta. {can} leer el aviso de "
        f"privacidad aquí: {notice_url(office)}\n\n{agree}"
    )


def answer_from_messages(raw_messages: list[dict[str, Any]]) -> Optional[tuple[bool, str]]:
    """(accepted, message_id) from a tapped consent button, if one is in the burst."""
    for message in raw_messages:
        if message.get("type") != "interactive":
            continue
        reply = (message.get("interactive") or {}).get("button_reply") or {}
        if reply.get("id") == BUTTON_ACCEPT:
            return True, message.get("id", "")
        if reply.get("id") == BUTTON_DECLINE:
            return False, message.get("id", "")
    return None


def answer_from_text(text: str) -> Optional[bool]:
    """A typed yes/no to the pending consent question; None when it's something else.

    Only consulted while the question is pending, and only for short, plain
    answers — "sí, pero mejor el martes" is not an answer to this question.
    """
    return plain_yes_no(text)


async def has_consented(db: AsyncSession, office_id: uuid.UUID, whatsapp_id: str) -> bool:
    """Whether this number accepted the current notice (always True when disabled)."""
    if not settings.privacy_consent_required:
        return True
    row = (
        await db.execute(
            select(PrivacyConsent.accepted).where(
                PrivacyConsent.office_id == office_id,
                PrivacyConsent.whatsapp_id == whatsapp_id,
                PrivacyConsent.notice_version == PRIVACY_NOTICE_VERSION,
            )
        )
    ).scalar_one_or_none()
    return bool(row)


async def record_answer(
    db: AsyncSession,
    office_id: uuid.UUID,
    whatsapp_id: str,
    accepted: bool,
    evidence_message_id: str = "",
) -> None:
    """Store (or overwrite) this number's answer to the current notice."""
    row = (
        await db.execute(
            select(PrivacyConsent).where(
                PrivacyConsent.office_id == office_id,
                PrivacyConsent.whatsapp_id == whatsapp_id,
                PrivacyConsent.notice_version == PRIVACY_NOTICE_VERSION,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        row = PrivacyConsent(
            id=uuid.uuid4(),
            office_id=office_id,
            whatsapp_id=whatsapp_id,
            notice_version=PRIVACY_NOTICE_VERSION,
        )
        db.add(row)
    row.accepted = accepted
    row.evidence_message_id = evidence_message_id or None
    row.decided_at = now_mx()
    await db.flush()
    logger.info(
        "privacy_consent_recorded",
        office_id=str(office_id),
        accepted=accepted,
        version=PRIVACY_NOTICE_VERSION,
    )


async def send_consent_request(meta_client, office: Office, whatsapp_id: str) -> tuple[str, Optional[str]]:
    """Send the fixed consent question with Acepto / No acepto. Returns (text, message_id).

    Always inside the 24h window: it goes out as the reply to the patient's
    own message.
    """
    text = consent_request_text(office)
    message_id = await meta_client.send_interactive_buttons(
        phone_number_id=office.whatsapp_phone_id,
        token=office.whatsapp_token,
        to=whatsapp_id,
        body_text=text,
        buttons=[
            {"id": BUTTON_ACCEPT, "title": "Acepto"},
            {"id": BUTTON_DECLINE, "title": "No acepto"},
        ],
    )
    return text, message_id
