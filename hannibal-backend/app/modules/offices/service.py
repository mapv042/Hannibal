"""Service layer for office CRUD operations."""

from __future__ import annotations

from uuid import UUID
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Office
from app.modules.offices.schemas import (
    CreateOfficeRequest,
    UpdateOfficeRequest,
)
from app.core.exceptions import NotFoundError
from app.utils.logger import get_logger

logger = get_logger(__name__)


async def create_office(
    data: CreateOfficeRequest,
    user_id: UUID,
    db: AsyncSession,
) -> Office:
    """
    Create a new office.

    Args:
        data: Office creation data
        user_id: User ID (owner)
        db: Database session

    Returns:
        Created Office object
    """
    office = Office(
        user_id=user_id,
        name=data.name,
        specialty=data.specialty,
        whatsapp_phone=data.whatsapp_phone,
        city=data.city,
        address=data.address,
    )

    db.add(office)
    await db.commit()
    await db.refresh(office)

    logger.info(
        "office_created",
        office_id=str(office.id),
        user_id=str(user_id),
        name=data.name,
    )

    return office


async def get_office(
    office_id: UUID,
    user_id: UUID,
    db: AsyncSession,
) -> Office:
    """
    Get a single office.

    Args:
        office_id: Office ID
        user_id: User ID (for authorization)
        db: Database session

    Returns:
        Office object

    Raises:
        NotFoundError: If office not found
    """
    office = await db.get(Office, office_id)

    if not office or office.user_id != user_id:
        raise NotFoundError("Office not found")

    return office


async def list_offices(
    user_id: UUID,
    db: AsyncSession,
) -> List[Office]:
    """
    List all offices for a user.

    Args:
        user_id: User ID
        db: Database session

    Returns:
        List of Office objects
    """
    result = await db.execute(
        select(Office).where(Office.user_id == user_id)
    )
    return result.scalars().all()


async def update_office(
    office_id: UUID,
    user_id: UUID,
    data: UpdateOfficeRequest,
    db: AsyncSession,
) -> Office:
    """
    Update an office.

    Args:
        office_id: Office ID
        user_id: User ID (for authorization)
        data: Update data
        db: Database session

    Returns:
        Updated Office object

    Raises:
        NotFoundError: If office not found
    """
    office = await get_office(office_id, user_id, db)

    # Update fields
    if data.name is not None:
        office.name = data.name
    if data.specialty is not None:
        office.specialty = data.specialty
    if data.whatsapp_phone is not None:
        office.whatsapp_phone = data.whatsapp_phone
    if data.city is not None:
        office.city = data.city
    if data.address is not None:
        office.address = data.address
    if data.assistant_tone is not None:
        office.assistant_tone = data.assistant_tone
    if data.assistant_name is not None:
        office.assistant_name = data.assistant_name
    if data.is_active is not None:
        office.is_active = data.is_active

    await db.commit()
    await db.refresh(office)

    logger.info(
        "office_updated",
        office_id=str(office_id),
        user_id=str(user_id),
    )

    return office


async def delete_office(
    office_id: UUID,
    user_id: UUID,
    db: AsyncSession,
) -> None:
    """
    Delete an office.

    Args:
        office_id: Office ID
        user_id: User ID (for authorization)
        db: Database session

    Raises:
        NotFoundError: If office not found
    """
    office = await get_office(office_id, user_id, db)

    await db.delete(office)
    await db.commit()

    logger.info(
        "office_deleted",
        office_id=str(office_id),
        user_id=str(user_id),
    )
