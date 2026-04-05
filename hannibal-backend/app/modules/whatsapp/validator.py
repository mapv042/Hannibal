"""Webhook signature validation for Meta Cloud API."""

from __future__ import annotations

import hmac
import hashlib
from typing import Optional

from app.config import settings
from app.utils.logger import get_logger

logger = get_logger(__name__)


def validate_webhook_signature(payload: bytes, signature: str) -> bool:
    """
    Validate incoming webhook signature using HMAC-SHA256.

    Meta Cloud API signs all webhook payloads with HMAC-SHA256 using the
    APP_SECRET. This validates that the webhook came from Meta.

    Args:
        payload: Raw request body bytes
        signature: X-Hub-Signature header value (format: "sha256=...")

    Returns:
        True if signature is valid, False otherwise

    Raises:
        ValueError: If signature format is invalid or APP_SECRET is not configured
    """
    if not signature or not payload:
        logger.warning("signature_validation_missing_inputs", signature_present=bool(signature), payload_present=bool(payload))
        return False

    if not settings.meta_app_secret:
        logger.error("signature_validation_missing_secret", detail="META_APP_SECRET not configured")
        raise ValueError("META_APP_SECRET not configured in environment")

    # Parse signature header format: "sha256=<hash>"
    try:
        hash_method, hash_value = signature.split("=", 1)
    except ValueError:
        logger.warning("signature_validation_invalid_format", signature=signature)
        return False

    if hash_method.lower() != "sha256":
        logger.warning("signature_validation_unsupported_method", method=hash_method)
        return False

    # Calculate expected signature
    expected_signature = hmac.new(
        settings.meta_app_secret.encode("utf-8"),
        payload,
        hashlib.sha256,
    ).hexdigest()

    # Constant-time comparison to prevent timing attacks
    is_valid = hmac.compare_digest(expected_signature, hash_value)

    if not is_valid:
        logger.warning(
            "signature_validation_failed",
            provided=hash_value[:8] + "...",
            expected=expected_signature[:8] + "...",
        )

    return is_valid
