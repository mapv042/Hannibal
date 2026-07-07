from __future__ import annotations

from typing import TYPE_CHECKING, AsyncGenerator

import redis.asyncio as aioredis
from fastapi import Depends, Header
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.security import validate_jwt
from app.db.base import get_async_session_maker

if TYPE_CHECKING:
    pass


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    Async database session dependency.

    Yields:
        AsyncSession for database operations
    """
    async with get_async_session_maker()() as session:
        try:
            yield session
        finally:
            await session.close()


async def get_current_user(
    authorization: str | None = Header(None),
) -> dict:
    """
    Extract and validate JWT from Authorization header.

    Args:
        authorization: Authorization header (format: "Bearer <token>")

    Returns:
        Decoded JWT payload

    Raises:
        UnauthorizedError: If token is missing or invalid
    """
    from app.core.exceptions import UnauthorizedError

    if not authorization:
        raise UnauthorizedError("Missing authorization header")

    try:
        scheme, token = authorization.split(" ")
        if scheme.lower() != "bearer":
            raise UnauthorizedError("Invalid authorization scheme")
    except ValueError as e:
        raise UnauthorizedError("Invalid authorization header format") from e

    return validate_jwt(token)


async def get_office(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Get office for the authenticated user.

    Args:
        current_user: Current user from JWT
        db: Database session

    Returns:
        Office object

    Raises:
        NotFoundError: If office not found
    """
    from sqlalchemy import select

    from app.core.exceptions import NotFoundError
    from app.db.models import Office

    user_id = current_user.get("sub")

    result = await db.execute(
        select(Office).where(Office.user_id == user_id),
    )
    office = result.scalar_one_or_none()

    if not office:
        raise NotFoundError("Office not found")

    return office


# Shared Redis client: from_url creates a whole connection pool, so building
# one per request leaks connections. One lazily-created client serves all
# requests and is closed on app shutdown (see main.lifespan).
_redis_client: aioredis.Redis | None = None


async def get_redis() -> aioredis.Redis:
    """
    Get the shared Redis client (lazily created connection pool).

    Returns:
        Redis async client
    """
    global _redis_client
    if _redis_client is None:
        _redis_client = aioredis.from_url(settings.redis_url)
    return _redis_client


async def close_redis() -> None:
    """Close the shared Redis client (app shutdown)."""
    global _redis_client
    if _redis_client is not None:
        await _redis_client.close()
        _redis_client = None
