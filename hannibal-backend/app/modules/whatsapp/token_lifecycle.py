"""Keep each office's WhatsApp token alive.

The Embedded Signup configuration can only issue business tokens that expire 60
days after they are generated or refreshed (Meta ships no full-access template
with a non-expiring token). A token that expires takes the office's assistant
down silently, and once it is gone only the doctor re-running Embedded Signup
brings it back — Meta's refresh endpoint needs a still-valid token.

So the daily `tasks.maintain_whatsapp_accounts` asks Meta about every office's
token (`debug_token`: still valid? expires when?) and refreshes it once fewer
than `REFRESH_WHEN_DAYS_LEFT` days remain — about monthly, leaving ~30 daily
retries before a failure becomes an outage. A revoked token (the doctor removed
the app from their business portfolio) is caught by the same check.

Expiries are Meta's, so they use `real_now()`, never the simulator's clock.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.exceptions import WhatsAppError
from app.db.models import Office
from app.modules.whatsapp.provisioning import GRAPH_BASE_URL
from app.utils.dates import real_now
from app.utils.logger import get_logger

logger = get_logger(__name__)

REFRESH_WHEN_DAYS_LEFT = 30


@dataclass(frozen=True)
class TokenInfo:
    valid: bool
    # None = the token never expires.
    expires_at: Optional[datetime]
    error: Optional[str] = None


def _app_access_token() -> str:
    return f"{settings.meta_app_id}|{settings.meta_app_secret}"


async def inspect_token(token: str) -> TokenInfo:
    """Ask Meta whether a token is valid and when it expires.

    Raises:
        WhatsAppError: If Meta couldn't be asked. That is "couldn't check", not
            "invalid" — a Meta outage must not mark every office broken.
    """
    url = f"{GRAPH_BASE_URL}/debug_token"
    params = {"input_token": token, "access_token": _app_access_token()}
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(url, params=params)
    except httpx.HTTPError as e:
        raise WhatsAppError("Could not reach Meta to inspect the token") from e

    if response.status_code >= 400:
        logger.warning(
            "wa_token_inspect_failed",
            status_code=response.status_code,
            response_body=response.text,
        )
        raise WhatsAppError("Meta refused to inspect the token")

    data = response.json().get("data", {})
    if not data.get("is_valid"):
        reason = (data.get("error") or {}).get("message") or "Meta reports the token as invalid"
        return TokenInfo(valid=False, expires_at=None, error=reason)

    expires = data.get("expires_at") or 0
    return TokenInfo(
        valid=True,
        expires_at=datetime.fromtimestamp(expires, tz=timezone.utc) if expires else None,
    )


async def refresh_token(token: str) -> Tuple[str, Optional[datetime]]:
    """Exchange a still-valid expiring token for a fresh 60-day one.

    The old token keeps working until its own expiry, so messages in flight
    with it are unaffected.

    Returns:
        (new_token, expires_at); expires_at is None if Meta didn't say.

    Raises:
        WhatsAppError: If the refresh fails.
    """
    url = f"{GRAPH_BASE_URL}/oauth/access_token"
    params = {
        "grant_type": "fb_exchange_token",
        "client_id": settings.meta_app_id,
        "client_secret": settings.meta_app_secret,
        "set_token_expires_in_60_days": "true",
        "fb_exchange_token": token,
    }
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(url, params=params)
    except httpx.HTTPError as e:
        raise WhatsAppError("Could not reach Meta to refresh the token") from e

    if response.status_code >= 400:
        logger.error(
            "wa_token_refresh_meta_error",
            status_code=response.status_code,
            response_body=response.text,
        )
        raise WhatsAppError(f"Meta refused the token refresh (HTTP {response.status_code})")

    data = response.json()
    new_token = data.get("access_token")
    if not new_token:
        raise WhatsAppError("Meta returned no token on refresh")
    expires_in = data.get("expires_in")
    expires_at = real_now() + timedelta(seconds=int(expires_in)) if expires_in else None
    return new_token, expires_at


async def maintain_office_token(office: Office, db: AsyncSession) -> str:
    """Check the office's token and refresh it when it nears expiry.

    Returns one of: "ok", "refreshed", "invalid", "refresh_failed",
    "check_failed". Every outcome but "ok"/"refreshed" logs an error (and so
    reaches Sentry) because each one ends with the assistant going silent.
    """
    office_id = str(office.id)
    try:
        info = await inspect_token(office.whatsapp_token)
    except WhatsAppError as e:
        logger.warning("wa_token_check_failed", office_id=office_id, error=str(e))
        return "check_failed"

    now = real_now()
    office.whatsapp_token_checked_at = now

    if not info.valid:
        office.whatsapp_token_error = info.error
        await db.commit()
        logger.error("wa_token_invalid", office_id=office_id, reason=info.error)
        return "invalid"

    office.whatsapp_token_expires_at = info.expires_at
    if info.expires_at is None or info.expires_at - now > timedelta(days=REFRESH_WHEN_DAYS_LEFT):
        office.whatsapp_token_error = None
        await db.commit()
        return "ok"

    days_left = (info.expires_at - now).days
    try:
        new_token, expires_at = await refresh_token(office.whatsapp_token)
    except WhatsAppError as e:
        office.whatsapp_token_error = f"Refresh failed: {e}"
        await db.commit()
        logger.error(
            "wa_token_refresh_failed", office_id=office_id, days_left=days_left, error=str(e)
        )
        return "refresh_failed"

    if expires_at is None:
        # Meta didn't say; ask, so the next run doesn't refresh again tomorrow.
        try:
            expires_at = (await inspect_token(new_token)).expires_at
        except WhatsAppError:
            expires_at = now + timedelta(days=60)

    office.whatsapp_token = new_token  # re-encrypted on write by EncryptedText
    office.whatsapp_token_expires_at = expires_at
    office.whatsapp_token_error = None
    await db.commit()
    logger.info(
        "wa_token_refreshed",
        office_id=office_id,
        previous_days_left=days_left,
        expires_at=expires_at.isoformat() if expires_at else None,
    )
    return "refreshed"
