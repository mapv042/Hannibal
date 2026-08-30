"""WhatsApp number provisioning and registration with Meta/Twilio."""

from __future__ import annotations

from typing import Optional, Dict, Any
import uuid
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import httpx

from app.config import settings
from app.utils.logger import get_logger
from app.db.models import Office
from app.core.exceptions import WhatsAppError

logger = get_logger(__name__)

TWILIO_BASE_URL = "https://api.twilio.com"
GRAPH_BASE_URL = "https://graph.facebook.com/v21.0"


def _compact_phone(display_phone_number: str) -> str:
    """Meta returns display numbers like '+52 1 33 1234 5678'; the column is
    String(20), so keep only '+' and digits."""
    return "".join(c for c in display_phone_number if c.isdigit() or c == "+")


async def exchange_code_for_token(code: str) -> str:
    """
    Exchange an Embedded Signup authorization code for a business token.

    The frontend never sees the token: FB.login(response_type='code') hands it
    a one-time code, and only the backend (holding META_APP_SECRET) can turn
    that into the long-lived business integration system user token.

    Raises:
        WhatsAppError: If the exchange fails or returns no token
    """
    url = f"{GRAPH_BASE_URL}/oauth/access_token"
    params = {
        "client_id": settings.meta_app_id,
        "client_secret": settings.meta_app_secret,
        "code": code,
    }
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(url, params=params)
    except httpx.HTTPError as e:
        logger.error("es_code_exchange_transport_error", error=str(e))
        raise WhatsAppError("Could not reach Meta to exchange the signup code") from e

    if response.status_code >= 400:
        logger.error(
            "es_code_exchange_failed",
            status_code=response.status_code,
            response_body=response.text,
        )
        raise WhatsAppError("Failed to exchange Embedded Signup code for a token")

    token = response.json().get("access_token")
    if not token:
        logger.error("es_code_exchange_no_token")
        raise WhatsAppError("Meta returned no access token for the signup code")
    return token


async def fetch_phone_info(phone_number_id: str, access_token: str) -> Dict[str, Any]:
    """
    Fetch display number + verified name for a phone_number_id.

    Doubles as validation that the exchanged token actually grants access to
    the phone_number_id the client claimed — a forged or mismatched id fails
    here before anything is stored.

    Raises:
        WhatsAppError: If the phone number can't be read with this token
    """
    url = f"{GRAPH_BASE_URL}/{phone_number_id}"
    params = {"fields": "display_phone_number,verified_name"}
    headers = {"Authorization": f"Bearer {access_token}"}
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(url, params=params, headers=headers)
    except httpx.HTTPError as e:
        logger.error(
            "es_phone_info_transport_error",
            phone_number_id=phone_number_id,
            error=str(e),
        )
        raise WhatsAppError("Could not reach Meta to verify the phone number") from e

    if response.status_code >= 400:
        logger.error(
            "es_phone_info_failed",
            phone_number_id=phone_number_id,
            status_code=response.status_code,
            response_body=response.text,
        )
        raise WhatsAppError(
            "The signup token does not grant access to this phone number"
        )
    return response.json()


async def subscribe_app_to_waba(waba_id: str, access_token: str) -> None:
    """
    Subscribe our app to the customer's WABA so its webhook events (messages,
    statuses) are delivered to our app-level webhook URL.

    Raises:
        WhatsAppError: If the subscription call fails
    """
    url = f"{GRAPH_BASE_URL}/{waba_id}/subscribed_apps"
    headers = {"Authorization": f"Bearer {access_token}"}
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(url, headers=headers)
    except httpx.HTTPError as e:
        logger.error("es_waba_subscribe_transport_error", waba_id=waba_id, error=str(e))
        raise WhatsAppError("Could not reach Meta to subscribe to the WABA") from e

    if response.status_code >= 400:
        logger.error(
            "es_waba_subscribe_failed",
            waba_id=waba_id,
            status_code=response.status_code,
            response_body=response.text,
        )
        raise WhatsAppError("Failed to subscribe the app to the WhatsApp account")
    logger.info("es_waba_subscribed", waba_id=waba_id)


async def register_phone_for_cloud_api(
    phone_number_id: str, access_token: str
) -> bool:
    """
    Register the phone number for Cloud API messaging (POST /register).

    Best-effort by design: a number that is already registered (e.g. a
    coexistence number the customer's flow registered during QR pairing, or a
    reconnect) makes this call fail without meaning the onboarding failed. We
    log loudly and let the caller store credentials either way — an actually
    unregistered number will surface immediately on the first send attempt.

    Returns:
        True if Meta confirmed the registration, False if the call failed
    """
    url = f"{GRAPH_BASE_URL}/{phone_number_id}/register"
    headers = {"Authorization": f"Bearer {access_token}"}
    payload = {
        "messaging_product": "whatsapp",
        "pin": settings.meta_register_pin,
    }
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(url, json=payload, headers=headers)
    except httpx.HTTPError as e:
        logger.warning(
            "es_phone_register_transport_error",
            phone_number_id=phone_number_id,
            error=str(e),
        )
        return False

    if response.status_code >= 400:
        logger.warning(
            "es_phone_register_failed",
            phone_number_id=phone_number_id,
            status_code=response.status_code,
            response_body=response.text,
        )
        return False

    logger.info("es_phone_registered", phone_number_id=phone_number_id)
    return True


async def complete_embedded_signup(
    code: str,
    phone_number_id: str,
    waba_id: str,
    office_id: uuid.UUID,
    mode: str,
    db: AsyncSession,
) -> Dict[str, Any]:
    """
    Full server-side completion of Meta's Embedded Signup flow.

    Steps: exchange the code for a business token → verify the token grants
    access to the claimed phone number (and get its display number) →
    subscribe our app to the WABA's webhooks → register the number for Cloud
    API (best-effort) → persist credentials on the office.

    Returns:
        Dict with phone_number, verified_name and registered (bool)

    Raises:
        WhatsAppError: On any non-recoverable Meta API failure
        ValueError: If the office doesn't exist or the mode is invalid
    """
    access_token = await exchange_code_for_token(code)
    phone_info = await fetch_phone_info(phone_number_id, access_token)
    await subscribe_app_to_waba(waba_id, access_token)
    registered = await register_phone_for_cloud_api(phone_number_id, access_token)

    display_number = phone_info.get("display_phone_number") or ""
    await register_meta_number(
        phone_number_id=phone_number_id,
        waba_id=waba_id,
        access_token=access_token,
        office_id=office_id,
        mode=mode,
        db=db,
        phone_number=_compact_phone(display_number) if display_number else None,
    )

    return {
        "phone_number": display_number or None,
        "verified_name": phone_info.get("verified_name"),
        "registered": registered,
    }


async def buy_twilio_number(
    area_code: str = "33",
) -> str:
    """
    Purchase a virtual Mexican WhatsApp number from Twilio.

    Creates a new Twilio phone number in the specified area code
    and returns it in E.164 format (e.g., "+5213334445555").

    Args:
        area_code: Mexico area code (e.g., "33" for Guadalajara, "55" for CDMX)

    Returns:
        Phone number in E.164 format with + prefix

    Raises:
        WhatsAppError: If Twilio API call fails or number purchase fails
    """
    auth = (settings.twilio_account_sid, settings.twilio_auth_token)

    # Twilio API to list and purchase available numbers
    url = f"{TWILIO_BASE_URL}/2010-04-01/Accounts/{settings.twilio_account_sid}/AvailablePhoneNumbers/MX/Local.json"

    params = {
        "AreaCode": area_code,
        "SmsEnabled": "true",
        "MmsEnabled": "true",
        "Limit": 1,
    }

    try:
        async with httpx.AsyncClient() as client:
            # Get available numbers
            response = await client.get(
                url,
                params=params,
                auth=auth,
            )
            response.raise_for_status()

            available = response.json()
            available_numbers = available.get("available_phone_numbers", [])

            if not available_numbers:
                logger.error(
                    "twilio_no_available_numbers",
                    area_code=area_code,
                )
                raise WhatsAppError(f"No available numbers in area code {area_code}")

            phone_number = available_numbers[0].get("phone_number")

            # Purchase the number
            purchase_url = (
                f"{TWILIO_BASE_URL}/2010-04-01/Accounts/{settings.twilio_account_sid}/IncomingPhoneNumbers.json"
            )

            purchase_payload = {
                "PhoneNumber": phone_number,
                "FriendlyName": f"WhatsApp - {area_code}",
            }

            response = await client.post(
                purchase_url,
                data=purchase_payload,
                auth=auth,
            )
            response.raise_for_status()

            purchased = response.json()
            purchased_number = purchased.get("phone_number")

            logger.info(
                "twilio_number_purchased",
                phone_number=purchased_number,
                area_code=area_code,
            )

            return purchased_number

    except httpx.HTTPError as e:
        logger.error(
            "twilio_number_purchase_error",
            area_code=area_code,
            error=str(e),
        )
        raise WhatsAppError(f"Failed to purchase Twilio number: {str(e)}") from e


async def register_meta_number(
    phone_number_id: str,
    waba_id: str,
    access_token: str,
    office_id: uuid.UUID,
    mode: str,
    db: AsyncSession,
    phone_number: Optional[str] = None,
) -> bool:
    """
    Register a WhatsApp number with Meta Business Account.

    Stores the phone number and WABA (WhatsApp Business Account) credentials
    in the database. This associates the number with an office.

    Supported modes:
    - "coexistence": Doctor can manually send messages, bot detects echoes
    - "dedicated": Dedicated number for bot only
    - "new": Brand new setup

    Args:
        phone_number_id: Meta's phone number ID
        waba_id: WhatsApp Business Account ID
        access_token: Meta API access token (should be encrypted before storage)
        office_id: ID of the office to associate
        mode: Operating mode (coexistence|dedicated|new)
        db: Database session
        phone_number: Display phone number to store (compact, e.g. +5213312345678)

    Returns:
        True if registration was successful

    Raises:
        ValueError: If office not found or invalid mode
        WhatsAppError: If registration fails
    """
    if mode not in ("coexistence", "dedicated", "new"):
        raise ValueError(f"Invalid mode: {mode}. Must be one of: coexistence, dedicated, new")

    try:
        # Fetch office
        office = await db.get(Office, office_id)
        if not office:
            raise ValueError(f"Office {office_id} not found")

        # Update office with WhatsApp credentials
        office.whatsapp_phone_id = phone_number_id
        office.whatsapp_waba_id = waba_id
        office.whatsapp_token = access_token  # Encrypted at rest by EncryptedText
        office.whatsapp_mode = mode
        office.whatsapp_app_active = True
        if phone_number:
            office.whatsapp_phone = phone_number

        db.add(office)
        await db.commit()

        logger.info(
            "whatsapp_registered",
            office_id=str(office_id),
            phone_number_id=phone_number_id,
            mode=mode,
        )

        return True

    except Exception as e:
        await db.rollback()
        logger.error(
            "whatsapp_registration_error",
            office_id=str(office_id),
            error=str(e),
        )
        raise WhatsAppError(f"Failed to register WhatsApp number: {str(e)}") from e


async def get_whatsapp_status(
    office_id: uuid.UUID,
    db: AsyncSession,
) -> Dict[str, Any]:
    """
    Get WhatsApp activation status for an office.

    Returns comprehensive status information about the office's
    WhatsApp setup.

    Args:
        office_id: ID of the office
        db: Database session

    Returns:
        Dictionary with keys:
        - active: bool - Whether WhatsApp is configured and active
        - phone_number: str - WhatsApp number (if configured)
        - phone_number_id: str - Meta's phone number ID
        - waba_id: str - WhatsApp Business Account ID
        - mode: str - Operating mode (coexistence|dedicated|new)
        - registered_at: datetime - When WhatsApp was registered
        - configured_at: datetime - Last configuration update

    Raises:
        ValueError: If office not found
    """
    try:
        office = await db.get(Office, office_id)
        if not office:
            raise ValueError(f"Office {office_id} not found")

        return {
            "active": office.whatsapp_app_active,
            "phone_number": office.whatsapp_phone,
            "phone_number_id": office.whatsapp_phone_id,
            "waba_id": office.whatsapp_waba_id,
            "mode": office.whatsapp_mode,
            "registered_at": office.created_at,
            "configured_at": office.updated_at,
        }

    except Exception as e:
        logger.error(
            "whatsapp_status_error",
            office_id=str(office_id),
            error=str(e),
        )
        raise


async def deactivate_whatsapp(
    office_id: uuid.UUID,
    db: AsyncSession,
) -> bool:
    """
    Deactivate WhatsApp for an office.

    Marks WhatsApp as inactive without deleting credentials
    (allows for easy reactivation).

    Args:
        office_id: ID of the office
        db: Database session

    Returns:
        True if deactivation was successful

    Raises:
        ValueError: If office not found
    """
    try:
        office = await db.get(Office, office_id)
        if not office:
            raise ValueError(f"Office {office_id} not found")

        office.whatsapp_app_active = False
        db.add(office)
        await db.commit()

        logger.info(
            "whatsapp_deactivated",
            office_id=str(office_id),
        )

        return True

    except Exception as e:
        await db.rollback()
        logger.error(
            "whatsapp_deactivation_error",
            office_id=str(office_id),
            error=str(e),
        )
        return False


async def get_office_by_phone_id(
    phone_number_id: str,
    db: AsyncSession,
) -> Optional[Office]:
    """
    Look up an office by its WhatsApp phone number ID.

    Used when processing incoming webhook messages to identify
    which office the message is for.

    Args:
        phone_number_id: Meta's phone number ID
        db: Database session

    Returns:
        Office object if found, None otherwise
    """
    try:
        result = await db.execute(
            select(Office).where(
                Office.whatsapp_phone_id == phone_number_id
            )
        )
        return result.scalars().first()

    except Exception as e:
        logger.error(
            "get_office_by_phone_id_error",
            phone_number_id=phone_number_id,
            error=str(e),
        )
        return None
