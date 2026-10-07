"""Dashboard view of urgent-appointment requests (read-only).

The doctor approves or rejects them over WhatsApp (resolve_urgent_request);
the dashboard only shows what is waiting, so nothing urgent goes unseen.
"""

from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db, get_office
from app.db.models import Office
from app.modules.urgencies.service import get_pending_urgencies

router = APIRouter(tags=["Urgencies"])


class PendingUrgency(BaseModel):
    id: str
    patient_id: str
    patient_name: str
    reason: str
    preferred: str
    created_at: Optional[str] = None


@router.get("/pending", response_model=List[PendingUrgency])
async def list_pending_urgencies(
    db: AsyncSession = Depends(get_db),
    office: Office = Depends(get_office),
):
    """Urgent requests still waiting for the doctor's answer, oldest first."""
    return await get_pending_urgencies(office.id, db)
