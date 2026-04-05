"""JWT authentication middleware."""

from __future__ import annotations

from typing import Optional

from fastapi import HTTPException, status
from jose import JWTError, jwt

from app.config import settings
from app.utils.logger import get_logger

logger = get_logger(__name__)


def verify_token(token: str) -> dict:
    """
    Verify JWT token and return claims.

    Args:
        token: JWT token string

    Returns:
        Token claims dictionary

    Raises:
        HTTPException: If token is invalid or expired
    """
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=["HS256"],
        )
        return payload
    except JWTError as e:
        logger.warning("Token verification failed", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
            headers={"WWW-Authenticate": "Bearer"},
        )


def decode_token(token: str) -> Optional[dict]:
    """
    Decode JWT token without raising exceptions.

    Args:
        token: JWT token string

    Returns:
        Token claims if valid, None otherwise
    """
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=["HS256"],
        )
        return payload
    except JWTError:
        return None
