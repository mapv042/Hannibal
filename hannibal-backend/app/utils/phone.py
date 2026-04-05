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
