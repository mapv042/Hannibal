"""Service layer for time blocks operations."""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional
from uuid import UUID

import redis.asyncio as aioredis
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import TimeBlock
from app.modules.scheduling.availability import invalidate_availability_cache
from app.core.exceptions import NotFoundError
from app.utils.logger import get_logger

logger = get_logger(__name__)


async def create_block(
    office_id: UUID,
    start_date: datetime,
    end_date: datetime,
    reason: Optional[str],
    all_day: bool,
    db: AsyncSession,
    redis_client: aioredis.Redis,
) -> TimeBlock:
    """
    Create a time block (vacation, meeting, lunch, etc.).

    Args:
        office_id: Office ID
        start_date: Block start time
        end_date: Block end time
        reason: Block reason
        all_day: Whether block is all-day
        db: Database session
        redis_client: Redis client

    Returns:
        Created TimeBlock object
    """
    time_block = TimeBlock(
        office_id=office_id,
        start_date=start_date,
        end_date=end_date,
        reason=reason,
        all_day=all_day,
        origin="manual",
    )

    db.add(time_block)
    await db.flush()

    # Invalidate cache for affected dates
    current_date = start_date.date()
    while current_date <= end_date.date():
        await invalidate_availability_cache(office_id, current_date, redis_client)
        current_date += __import__("datetime").timedelta(days=1)

    await db.commit()
    await db.refresh(time_block)

    logger.info(
        "block_created",
        block_id=str(time_block.id),
        office_id=str(office_id),
        reason=reason,
    )

    return time_block


async def delete_block(
    block_id: UUID,
    office_id: UUID,
    db: AsyncSession,
    redis_client: aioredis.Redis,
) -> None:
    """
    Delete a time block.

    Args:
        block_id: TimeBlock ID
        office_id: Office ID
        db: Database session
        redis_client: Redis client

    Raises:
        NotFoundError: If block not found
    """
    time_block = await db.get(TimeBlock, block_id)
    if not time_block or time_block.office_id != office_id:
        raise NotFoundError("TimeBlock not found")

    start_date = time_block.start_date
    end_date = time_block.end_date

    await db.delete(time_block)

    # Invalidate cache for affected dates
    current_date = start_date.date()
    while current_date <= end_date.date():
        await invalidate_availability_cache(office_id, current_date, redis_client)
        current_date += __import__("datetime").timedelta(days=1)

    await db.commit()

    logger.info(
        "block_deleted",
        block_id=str(block_id),
        office_id=str(office_id),
    )


async def get_blocks(
    office_id: UUID,
    start_date: datetime,
    end_date: datetime,
    db: AsyncSession,
) -> List[TimeBlock]:
    """
    Get time blocks for a date range.

    Args:
        office_id: Office ID
        start_date: Range start date
        end_date: Range end date
        db: Database session

    Returns:
        List of TimeBlock objects
    """
    result = await db.execute(
        select(TimeBlock).where(
            and_(
                TimeBlock.office_id == office_id,
                TimeBlock.start_date >= start_date,
                TimeBlock.end_date <= end_date,
            )
        )
    )
    return result.scalars().all()
