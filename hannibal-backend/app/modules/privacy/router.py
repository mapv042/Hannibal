"""Public data for an office's privacy notice (no auth: patients open the link)."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db
from app.core.exceptions import NotFoundError
from app.db.models import Office
from app.modules.privacy.consent import PRIVACY_NOTICE_VERSION

router = APIRouter(tags=["Privacy"])


class PrivacyNoticeData(BaseModel):
    """Who is responsible for the patient's data, and how to reach them.

    Only what a privacy notice must publish anyway — nothing about patients,
    nothing that isn't already on the practice's door and WhatsApp profile.
    """

    office_name: str
    doctor_name: str | None
    address: str | None
    city: str | None
    state: str | None
    contact_email: str | None
    whatsapp_phone: str | None
    version: str


@router.get("/{office_id}", response_model=PrivacyNoticeData)
async def privacy_notice_data(office_id: UUID, db: AsyncSession = Depends(get_db)):
    office = await db.get(Office, office_id)
    if office is None or not office.is_active:
        raise NotFoundError("Office not found")
    doctor = " ".join(p for p in (office.doctor_first_name, office.doctor_last_name) if p) or None
    return PrivacyNoticeData(
        office_name=office.name,
        doctor_name=doctor,
        address=office.address,
        city=office.city,
        state=office.state,
        contact_email=office.privacy_contact_email,
        whatsapp_phone=office.whatsapp_phone,
        version=PRIVACY_NOTICE_VERSION,
    )
