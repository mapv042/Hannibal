"""FastAPI router for office endpoints."""

from __future__ import annotations

from uuid import UUID
from typing import List

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db, get_current_user
from app.modules.offices.schemas import (
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
