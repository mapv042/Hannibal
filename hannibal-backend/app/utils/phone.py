from __future__ import annotations

import re


def normalize_phone(phone: str) -> str:
    """
    Normalize Mexican phone number to +521XXXXXXXXXX format.

    Handles various input formats:
    - 10 digits: 5551234567 -> +525551234567
    - 11 digits starting with 1: 15551234567 -> +525551234567
    - With country code: +525551234567, 525551234567
    - With formatting: (555) 123-4567, 555.123.4567

    Args:
        phone: Phone number in various formats

    Returns:
        Normalized phone number in +521XXXXXXXXXX format
    """
    # Remove all non-digit characters except +
    cleaned = re.sub(r"[^\d+]", "", phone)

    # Remove leading +
    if cleaned.startswith("+"):
        cleaned = cleaned[1:]

    # Remove leading 52 (country code)
    if cleaned.startswith("52"):
        cleaned = cleaned[2:]

    # Handle 11 digits starting with 1 (legacy format)
    if len(cleaned) == 11 and cleaned.startswith("1"):
        cleaned = cleaned[1:]

    # Should have 10 digits now
    if len(cleaned) != 10:
        raise ValueError(f"Invalid phone number: {phone}")

    return f"+52{cleaned}"


def phone_core_digits(phone: str) -> str:
    """Return the 10-digit national core of a Mexican number (raises on invalid)."""
    return normalize_phone(phone)[3:]  # drop the leading "+52"


def to_whatsapp_id(phone: str) -> str:
    """Best-effort WhatsApp (Meta) id for a Mexican number: 521 + 10 digits.

    Matches the format Meta sends for Mexican mobiles, so a third party
    registered by phone is found if they later message the bot themselves.
    """
    return f"521{phone_core_digits(phone)}"


def phone_match_variants(phone: str) -> list[str]:
    """Equivalent string forms of a number, for matching DB columns that may
    store it un-normalized (raw WhatsApp id, +52…, 52…, or 10-digit)."""
    d = phone_core_digits(phone)
    return [f"+52{d}", f"52{d}", f"521{d}", d]


def format_display(phone: str) -> str:
    """
    Format phone number for display (readable format).

    Example: +525551234567 -> (555) 123-4567

    Args:
        phone: Normalized phone number

    Returns:
        Formatted phone number for display
    """
    # Normalize first if not already normalized
    if not phone.startswith("+52"):
        phone = normalize_phone(phone)

    # Remove +52 prefix for formatting
    digits = phone[3:]

    # Format as (555) 123-4567
    return f"({digits[:3]}) {digits[3:6]}-{digits[6:]}"


def display_or_raw(phone: str) -> str:
    """Readable display for a phone, falling back to the raw value if unparseable."""
    try:
        return format_display(phone)
    except ValueError:
        return phone
