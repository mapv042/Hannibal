"""FastAPI router for office endpoints."""

from __future__ import annotations

from uuid import UUID
from typing import List

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db, get_current_user, get_redis
from app.modules.whatsapp.coexistence import (
    DEFAULT_DOCTOR_TAKEOVER_PAUSE_MINUTES,
    get_pause_until,
    pause_bot,
    resume_bot,
)
from app.modules.offices.schemas import (
    BotStatusResponse,
    PauseBotRequest,
    CreateOfficeRequest,
    UpdateOfficeRequest,
    OfficeResponse,
    ReminderRuleSchema,
    UpdateReminderRulesRequest,
)
from app.modules.offices.service import (
    create_office,
    get_office,
    list_offices,
    update_office,
    delete_office,
    get_reminder_rules,
    replace_reminder_rules,
)
from app.modules.offices.stats import get_office_stats
from app.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(tags=["Offices"])


@router.post("", response_model=OfficeResponse, status_code=201)
async def create_office_endpoint(
    request: CreateOfficeRequest,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Create a new office.

    Request Body:
        name: Office name (required)
        specialty: Medical specialty (optional)
        whatsapp_phone: WhatsApp phone number (optional)
        city: City (optional)
        address: Address (optional)

    Returns:
        Created office
    """
    logger.info(
        "create_office",
        user_id=current_user.get("sub"),
        name=request.name,
    )

    office = await create_office(
        data=request,
        user_id=UUID(current_user.get("sub")),
        db=db,
    )

    return office


@router.get("", response_model=List[OfficeResponse])
async def list_offices_endpoint(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    List all offices for the current user.

    Returns:
        List of offices
    """
    logger.info(
        "list_offices",
        user_id=current_user.get("sub"),
    )

    offices = await list_offices(
        user_id=UUID(current_user.get("sub")),
        db=db,
    )

    return offices


@router.get("/{office_id}", response_model=OfficeResponse)
async def get_office_endpoint(
    office_id: UUID,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get a specific office."""
    logger.info(
        "get_office",
        office_id=str(office_id),
        user_id=current_user.get("sub"),
    )

    office = await get_office(
        office_id=office_id,
        user_id=UUID(current_user.get("sub")),
        db=db,
    )

    return office


@router.put("/{office_id}", response_model=OfficeResponse)
async def update_office_endpoint(
    office_id: UUID,
    request: UpdateOfficeRequest,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update an office."""
    logger.info(
        "update_office",
        office_id=str(office_id),
        user_id=current_user.get("sub"),
    )

    office = await update_office(
        office_id=office_id,
        user_id=UUID(current_user.get("sub")),
        data=request,
        db=db,
    )

    return office


@router.delete("/{office_id}", status_code=204)
async def delete_office_endpoint(
    office_id: UUID,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete an office."""
    logger.info(
        "delete_office",
        office_id=str(office_id),
        user_id=current_user.get("sub"),
    )

    await delete_office(
        office_id=office_id,
        user_id=UUID(current_user.get("sub")),
        db=db,
    )


@router.get("/{office_id}/reminder-rules", response_model=List[ReminderRuleSchema])
async def get_reminder_rules_endpoint(
    office_id: UUID,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get the reminder configuration for an office (defaults if none set)."""
    rules = await get_reminder_rules(
        office_id=office_id,
        user_id=UUID(current_user.get("sub")),
        db=db,
    )
    return rules


@router.put("/{office_id}/reminder-rules", response_model=List[ReminderRuleSchema])
async def update_reminder_rules_endpoint(
    office_id: UUID,
    request: UpdateReminderRulesRequest,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Replace the full set of reminder rules for an office."""
    logger.info(
        "update_reminder_rules",
        office_id=str(office_id),
        user_id=current_user.get("sub"),
        count=len(request.rules),
    )

    rules = await replace_reminder_rules(
        office_id=office_id,
        user_id=UUID(current_user.get("sub")),
        rules=request.rules,
        db=db,
    )
    return rules


@router.get("/{office_id}/stats")
async def get_office_stats_endpoint(
    office_id: UUID,
    period: str = Query("month", pattern="^(week|month|quarter)$"),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Practice health metrics for the dashboard, with period-over-period change."""
    # Authorization: resolves the office from the JWT and 404s if not owned.
    await get_office(office_id, UUID(current_user.get("sub")), db)
    return await get_office_stats(db, office_id, period)  # type: ignore[arg-type]


async def _bot_status(office_id: UUID, redis_client: aioredis.Redis) -> BotStatusResponse:
    paused_until = await get_pause_until(office_id, redis_client)
    return BotStatusResponse(
        bot_status="paused" if paused_until else "active",
        paused_until=paused_until,
    )


@router.get("/{office_id}/bot-status", response_model=BotStatusResponse)
async def get_bot_status_endpoint(
    office_id: UUID,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    redis_client: aioredis.Redis = Depends(get_redis),
):
    """Whether the assistant is answering patients, read from the pause key."""
    await get_office(office_id, UUID(current_user.get("sub")), db)
    return await _bot_status(office_id, redis_client)


@router.post("/{office_id}/pause", response_model=BotStatusResponse)
async def pause_bot_endpoint(
    office_id: UUID,
    request: PauseBotRequest | None = None,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    redis_client: aioredis.Redis = Depends(get_redis),
):
    """Pause the assistant office-wide — the same pause the doctor's pause_bot tool sets."""
    await get_office(office_id, UUID(current_user.get("sub")), db)
    minutes = request.minutes if request else DEFAULT_DOCTOR_TAKEOVER_PAUSE_MINUTES
    if not await pause_bot(office_id, minutes, redis_client):
        raise HTTPException(status_code=503, detail="No se pudo pausar el asistente")
    return await _bot_status(office_id, redis_client)


@router.post("/{office_id}/resume", response_model=BotStatusResponse)
async def resume_bot_endpoint(
    office_id: UUID,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    redis_client: aioredis.Redis = Depends(get_redis),
):
    """Lift the office-wide pause."""
    await get_office(office_id, UUID(current_user.get("sub")), db)
    if not await resume_bot(office_id, redis_client):
        raise HTTPException(status_code=503, detail="No se pudo reanudar el asistente")
    return await _bot_status(office_id, redis_client)
