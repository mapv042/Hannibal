"""Service layer for office CRUD operations."""

from __future__ import annotations

from uuid import UUID
from typing import List, Optional

from fastapi import HTTPException
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import ReminderType
from app.db.models import Office, ReminderRule
from app.modules.offices.schemas import (
    CreateOfficeRequest,
    UpdateOfficeRequest,
    ReminderRuleSchema,
)
from app.modules.reminders.rules import default_reminder_rules
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
        owner_phone=data.owner_phone,
        city=data.city,
        state=data.state,
        address=data.address,
    )

    # Seed the office with the default reminder configuration so doctors get
    # sensible reminders immediately and can tweak them later.
    for rule in default_reminder_rules():
        rule.office = office
        db.add(rule)

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
    if data.owner_phone is not None:
        office.owner_phone = data.owner_phone
    if data.city is not None:
        office.city = data.city
    if data.address is not None:
        office.address = data.address
    if data.assistant_tone is not None:
        office.assistant_tone = data.assistant_tone
    if data.assistant_name is not None:
        office.assistant_name = data.assistant_name
    if data.custom_prompt is not None:
        office.custom_prompt = data.custom_prompt
    if data.is_active is not None:
        office.is_active = data.is_active
    if data.onboarding_completed is not None:
        office.onboarding_completed = data.onboarding_completed
    if data.state is not None:
        office.state = data.state
    if data.welcome_message is not None:
        office.welcome_message = data.welcome_message
    if data.new_patient_duration_min is not None:
        office.new_patient_duration_min = data.new_patient_duration_min
    if data.returning_patient_duration_min is not None:
        office.returning_patient_duration_min = data.returning_patient_duration_min
    if data.new_patient_cost is not None:
        office.new_patient_cost = data.new_patient_cost
    if data.returning_patient_cost is not None:
        office.returning_patient_cost = data.returning_patient_cost
    if data.notify_new_appointment is not None:
        office.notify_new_appointment = data.notify_new_appointment
    if data.notify_cancellation is not None:
        office.notify_cancellation = data.notify_cancellation
    if data.notify_new_patient is not None:
        office.notify_new_patient = data.notify_new_patient
    if data.notify_unconfirmed is not None:
        office.notify_unconfirmed = data.notify_unconfirmed

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


async def get_reminder_rules(
    office_id: UUID,
    user_id: UUID,
    db: AsyncSession,
) -> List[ReminderRule]:
    """
    Return the reminder rules configured for an office.

    Falls back to the default rules (without persisting them) for offices that
    have none yet, so the API always reflects what will actually be sent.
    """
    await get_office(office_id, user_id, db)  # authorization check

    result = await db.execute(
        select(ReminderRule).where(ReminderRule.office_id == office_id)
    )
    rules = result.scalars().all()
    if rules:
        return rules

    # No rows yet: return defaults so the caller sees the effective config.
    return default_reminder_rules()


async def replace_reminder_rules(
    office_id: UUID,
    user_id: UUID,
    rules: List["ReminderRuleSchema"],
    db: AsyncSession,
) -> List[ReminderRule]:
    """
    Replace the full set of reminder rules for an office.

    Args:
        office_id: Office ID
        user_id: User ID (for authorization)
        rules: Complete desired set of rules
        db: Database session

    Returns:
        The persisted ReminderRule rows
    """
    await get_office(office_id, user_id, db)  # authorization check

    # Validate reminder types
    valid_types = {rt.value for rt in ReminderType}
    for rule in rules:
        if rule.reminder_type not in valid_types:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Invalid reminder_type '{rule.reminder_type}'. "
                    f"Allowed: {', '.join(sorted(valid_types))}"
                ),
            )

    # Replace strategy: delete existing rows, insert the new set.
    await db.execute(
        delete(ReminderRule).where(ReminderRule.office_id == office_id)
    )

    new_rules = [
        ReminderRule(
            office_id=office_id,
            reminder_type=rule.reminder_type,
            offset_minutes=rule.offset_minutes,
            enabled=rule.enabled,
        )
        for rule in rules
    ]
    db.add_all(new_rules)
    await db.commit()

    logger.info(
        "reminder_rules_updated",
        office_id=str(office_id),
        user_id=str(user_id),
        count=len(new_rules),
    )

    return new_rules
