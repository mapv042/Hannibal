"""Google OAuth2 authentication flow for Google Calendar integration."""

from __future__ import annotations

import secrets
from typing import Optional
from uuid import UUID

import redis.asyncio as aioredis
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.config import settings
from app.db.models import Office
from app.core.exceptions import GoogleCalendarError
from app.utils.dates import now_mx
from app.utils.logger import get_logger

logger = get_logger(__name__)

# OAuth state: an unguessable, single-use nonce mapped to the office id in Redis.
# This is the CSRF defense — the callback trusts the office only if it presents
# a nonce we minted, so an attacker can't forge a callback that binds their
# authorization code (or their calendar) to someone else's office.
OAUTH_STATE_KEY = "gcal_oauth_state:{nonce}"
OAUTH_STATE_TTL = 600  # 10 minutes to complete the consent flow


async def get_google_oauth_url(office_id: UUID, redis_client: aioredis.Redis) -> str:
    """
    Generate a Google OAuth2 authorization URL with a CSRF-safe state nonce.

    Args:
        office_id: Office ID
        redis_client: Redis client used to store the state → office mapping

    Returns:
        Authorization URL
    """
    import urllib.parse

    nonce = secrets.token_urlsafe(32)
    await redis_client.setex(
        OAUTH_STATE_KEY.format(nonce=nonce), OAUTH_STATE_TTL, str(office_id)
    )

    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": settings.google_redirect_uri,
        "response_type": "code",
        "scope": " ".join(
            [
                "https://www.googleapis.com/auth/calendar",
                "https://www.googleapis.com/auth/calendar.events",
            ]
        ),
        "access_type": "offline",
        "prompt": "consent",
        "state": nonce,
    }

    return f"https://accounts.google.com/o/oauth2/v2/auth?{urllib.parse.urlencode(params)}"


async def resolve_oauth_state(state: str, redis_client: aioredis.Redis) -> UUID:
    """Resolve (and consume) an OAuth state nonce to its office id.

    Single-use: the nonce is deleted on lookup so a leaked callback URL can't
    be replayed. Raises GoogleCalendarError if the nonce is unknown/expired.
    """
    key = OAUTH_STATE_KEY.format(nonce=state)
    office_id_str = await redis_client.get(key)
    if not office_id_str:
        raise GoogleCalendarError("Invalid or expired OAuth state")
    await redis_client.delete(key)
    if isinstance(office_id_str, bytes):
        office_id_str = office_id_str.decode()
    return UUID(office_id_str)


async def exchange_code_for_token(
    code: str,
    office_id: UUID,
    db: AsyncSession,
) -> dict:
    """
    Exchange authorization code for access/refresh tokens.

    Args:
        code: OAuth2 authorization code
        office_id: Office ID
        db: Database session

    Returns:
        Token data {access_token, refresh_token, expires_at, ...}

    Raises:
        GoogleCalendarError: If token exchange fails
    """
    import httpx
    from datetime import datetime, timedelta, timezone

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://oauth2.googleapis.com/token",
                data={
                    "code": code,
                    "client_id": settings.google_client_id,
                    "client_secret": settings.google_client_secret,
                    "redirect_uri": settings.google_redirect_uri,
                    "grant_type": "authorization_code",
                },
            )

            if response.status_code != 200:
                logger.error(
                    "oauth_token_exchange_failed",
                    status_code=response.status_code,
                    response=response.text,
                )
                raise GoogleCalendarError("Failed to exchange authorization code")

            token_data = response.json()

            # Add expiry time
            if "expires_in" in token_data:
                token_data["expires_at"] = (
                    now_mx() + timedelta(seconds=token_data["expires_in"])
                ).isoformat()

            # Store token in office (encrypted at rest by the EncryptedJSON type)
            office = await db.get(Office, office_id)
            if not office:
                raise GoogleCalendarError("Office not found")

            office.google_calendar_token = token_data

            await db.commit()

            logger.info(
                "google_oauth_token_exchanged",
                office_id=str(office_id),
            )

            return token_data

    except Exception as e:
        logger.error(
            "error_exchange_google_oauth",
            office_id=str(office_id),
            error=str(e),
        )
        raise GoogleCalendarError(f"OAuth token exchange failed: {str(e)}")


async def refresh_google_token(
    office_id: UUID,
    db: AsyncSession,
) -> Optional[dict]:
    """
    Refresh expired Google OAuth token.

    Args:
        office_id: Office ID
        db: Database session

    Returns:
        Updated token data or None if refresh fails

    Raises:
        GoogleCalendarError: If refresh fails
    """
    import httpx
    from datetime import datetime, timedelta, timezone

    try:
        office = await db.get(Office, office_id)
        if not office or not office.google_calendar_token:
            raise GoogleCalendarError("No Google token found")

        token_data = office.google_calendar_token
        refresh_token = token_data.get("refresh_token")

        if not refresh_token:
            raise GoogleCalendarError("No refresh token available")

        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://oauth2.googleapis.com/token",
                data={
                    "client_id": settings.google_client_id,
                    "client_secret": settings.google_client_secret,
                    "refresh_token": refresh_token,
                    "grant_type": "refresh_token",
                },
            )

            if response.status_code != 200:
                logger.error(
                    "token_refresh_failed",
                    status_code=response.status_code,
                    office_id=str(office_id),
                )
                raise GoogleCalendarError("Failed to refresh token")

            new_token_data = response.json()
            new_token_data["refresh_token"] = (
                refresh_token  # Preserve refresh token
            )
            new_token_data["expires_at"] = (
                now_mx() + timedelta(seconds=new_token_data["expires_in"])
            ).isoformat()

            office.google_calendar_token = new_token_data
            await db.commit()

            logger.info(
                "google_token_refreshed",
                office_id=str(office_id),
            )

            return new_token_data

    except Exception as e:
        logger.error(
            "error_refresh_google_token",
            office_id=str(office_id),
            error=str(e),
        )
        raise


async def get_valid_google_token(
    office_id: UUID,
    db: AsyncSession,
) -> str:
    """
    Get a valid Google access token, refreshing if necessary.

    Args:
        office_id: Office ID
        db: Database session

    Returns:
        Valid access token

    Raises:
        GoogleCalendarError: If token is not available
    """
    from datetime import datetime, timedelta, timezone

    office = await db.get(Office, office_id)
    if not office or not office.google_calendar_token:
        raise GoogleCalendarError("No Google token found")

    token_data = office.google_calendar_token
    access_token = token_data.get("access_token")
    expires_at_str = token_data.get("expires_at")

    # Check if token is expired or about to expire (5 min buffer)
    if expires_at_str:
        expires_at = datetime.fromisoformat(expires_at_str)
        # Tokens persisted before the tz migration are naive UTC wall-clock —
        # normalize them to UTC so the comparison never mixes naive and aware.
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if now_mx() >= expires_at - timedelta(minutes=5):
            # Token expired, refresh it
            new_token = await refresh_google_token(office_id, db)
            return new_token.get("access_token", access_token)

    return access_token
