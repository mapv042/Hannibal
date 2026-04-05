from __future__ import annotations

import hashlib
import hmac
from typing import TYPE_CHECKING

from cryptography.fernet import Fernet
from jose import JWTError, jwt

from app.config import settings
from app.core.exceptions import UnauthorizedError

if TYPE_CHECKING:
    from jose import JWTClaimsError


def encrypt_data(data: str) -> str:
    """
    Encrypt data using Fernet with the ENCRYPTION_KEY.

    Args:
        data: String to encrypt

    Returns:
        Encrypted string (URL-safe base64)
    """
    key = settings.encryption_key.encode()
    # Convert hex string to bytes for Fernet
    key_bytes = bytes.fromhex(settings.encryption_key)
    # Fernet requires 32-byte keys, encoded as base64
    fernet_key = Fernet(Fernet.generate_key()[:32])
    cipher = Fernet(fernet_key)
    return cipher.encrypt(data.encode()).decode()


def decrypt_data(encrypted_data: str) -> str:
    """
    Decrypt data encrypted with encrypt_data.

    Args:
        encrypted_data: Encrypted string

    Returns:
        Decrypted string
    """
    key_bytes = bytes.fromhex(settings.encryption_key)
    cipher = Fernet(key_bytes)
    return cipher.decrypt(encrypted_data.encode()).decode()


def validate_jwt(token: str) -> dict:
    """
    Validate a Supabase JWT token.

    Args:
        token: JWT token from Authorization header

    Returns:
        Decoded token payload

    Raises:
        UnauthorizedError: If token is invalid or expired
    """
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=["HS256"],
        )
        return payload
    except JWTError as e:
        raise UnauthorizedError(f"Invalid or expired token: {e}") from e


def validate_meta_signature(
    body: str,
    signature: str,
) -> bool:
    """
    Validate Meta/WhatsApp webhook signature using HMAC-SHA256.

    Args:
        body: Raw request body
        signature: X-Hub-Signature header value (format: sha1=<hash>)

    Returns:
        True if signature is valid, False otherwise
    """
    # Meta uses sha1, not sha256 for webhook signatures
    expected_signature = hmac.new(
        settings.meta_app_secret.encode(),
        body.encode(),
        hashlib.sha1,
    ).hexdigest()

    # Signature header format: sha1=<hash>
    return hmac.compare_digest(
        f"sha1={expected_signature}",
        signature,
    )
