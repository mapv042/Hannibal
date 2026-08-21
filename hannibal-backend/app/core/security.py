from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import time
from typing import TYPE_CHECKING

import httpx
from cryptography.fernet import Fernet
from jose import JWTError, jwt

from app.config import settings
from app.core.exceptions import UnauthorizedError
from app.utils.logger import get_logger

logger = get_logger(__name__)

if TYPE_CHECKING:
    from jose import JWTClaimsError


def _fernet() -> Fernet:
    """Build the Fernet cipher from ENCRYPTION_KEY (64-char hex → 32 bytes)."""
    key_bytes = bytes.fromhex(settings.encryption_key)
    return Fernet(base64.urlsafe_b64encode(key_bytes))


def encrypt_data(data: str) -> str:
    """
    Encrypt data using Fernet with the ENCRYPTION_KEY.

    Args:
        data: String to encrypt

    Returns:
        Encrypted string (URL-safe base64)
    """
    return _fernet().encrypt(data.encode()).decode()


def decrypt_data(encrypted_data: str) -> str:
    """
    Decrypt data encrypted with encrypt_data.

    Args:
        encrypted_data: Encrypted string

    Returns:
        Decrypted string

    Raises:
        cryptography.fernet.InvalidToken: If the value was not encrypted
            with the current ENCRYPTION_KEY.
    """
    return _fernet().decrypt(encrypted_data.encode()).decode()


# Supabase signs access tokens with an asymmetric key (ECC P-256 → ES256) since
# the "JWT Signing Keys" migration; the legacy HS256 shared secret is kept only
# to verify tokens minted before the rotation. Accept both, but pick the key
# material from the header's `alg`: HS256 always uses the shared secret and the
# asymmetric algorithms always use a public key from the JWKS. Never the other
# way around — verifying an HS256 token with a JWKS public key as the secret is
# the classic algorithm-confusion forgery, since that public key is published.
_ASYMMETRIC_ALGORITHMS = frozenset({"ES256", "ES384", "ES512", "RS256", "RS384", "RS512"})

_JWKS_TTL_SECONDS = 3600.0
# Floor between forced refetches so an unknown `kid` can't be used to make us
# hammer the auth server.
_JWKS_MIN_REFETCH_SECONDS = 60.0

_jwks_lock = asyncio.Lock()
_jwks_keys: dict[str, dict] = {}
_jwks_fetched_at: float = 0.0


def _jwks_url() -> str:
    """Build the JWKS endpoint URL from SUPABASE_URL."""
    base = settings.supabase_url.rstrip("/")
    if not base:
        raise UnauthorizedError("Server auth is misconfigured (missing SUPABASE_URL)")
    return f"{base}/auth/v1/.well-known/jwks.json"


async def _load_jwks(force: bool = False) -> dict[str, dict]:
    """
    Return the Supabase signing keys, keyed by `kid`, refreshing when stale.

    Args:
        force: Refetch even if the cache is still fresh. Used when a token
            carries a `kid` we have not seen, which is how a key rotation
            surfaces.

    Returns:
        Mapping of `kid` to JWK.

    Raises:
        UnauthorizedError: If the keys cannot be fetched and none are cached.
    """
    global _jwks_keys, _jwks_fetched_at

    async with _jwks_lock:
        age = time.monotonic() - _jwks_fetched_at
        if _jwks_keys and age < (_JWKS_MIN_REFETCH_SECONDS if force else _JWKS_TTL_SECONDS):
            return _jwks_keys

        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(_jwks_url())
                response.raise_for_status()
                keys = {
                    key["kid"]: key
                    for key in response.json().get("keys", [])
                    if key.get("kid")
                }
        except Exception as e:
            if _jwks_keys:
                # Serving stale keys beats rejecting every request over a blip
                # in the auth server; the keys themselves are long-lived.
                logger.warning("jwks_refresh_failed_serving_cached", error=str(e))
                return _jwks_keys
            raise UnauthorizedError("Could not fetch token signing keys") from e

        _jwks_keys = keys
        _jwks_fetched_at = time.monotonic()
        logger.info("jwks_refreshed", key_count=len(keys))
        return _jwks_keys


async def _signing_key_for(header: dict) -> tuple[str | dict, str]:
    """Resolve the verification key and algorithm for a token header."""
    algorithm = header.get("alg")

    if algorithm == "HS256":
        # Refuse to validate with an empty secret: python-jose would happily
        # accept a token an attacker signed with the same empty secret, letting
        # them forge any `sub`. This guard holds regardless of environment.
        if not settings.jwt_secret:
            raise UnauthorizedError("Server auth is misconfigured (missing JWT secret)")
        return settings.jwt_secret, algorithm

    if algorithm in _ASYMMETRIC_ALGORITHMS:
        kid = header.get("kid")
        if not kid:
            raise UnauthorizedError("Token is missing a key id")
        keys = await _load_jwks()
        key = keys.get(kid)
        if key is None:
            # Unknown kid usually means Supabase rotated the signing key.
            key = (await _load_jwks(force=True)).get(kid)
        if key is None:
            raise UnauthorizedError("Token was signed with an unknown key")
        return key, algorithm

    raise UnauthorizedError(f"Unsupported token algorithm: {algorithm}")


async def validate_jwt(token: str) -> dict:
    """
    Validate a Supabase JWT token.

    Args:
        token: JWT token from Authorization header

    Returns:
        Decoded token payload

    Raises:
        UnauthorizedError: If token is invalid, expired, signed with an
            unsupported algorithm, or the server is misconfigured.
    """
    try:
        header = jwt.get_unverified_header(token)
    except JWTError as e:
        raise UnauthorizedError(f"Malformed token: {e}") from e

    key, algorithm = await _signing_key_for(header)

    try:
        return jwt.decode(
            token,
            key,
            algorithms=[algorithm],
            audience=settings.jwt_audience,
        )
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
