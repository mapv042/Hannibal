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
        office.whatsapp_token = access_token  # Should be encrypted in real implementation
        office.whatsapp_mode = mode
        office.whatsapp_app_active = True

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
            "phone_number": office.whatsapp_phone_number,
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
