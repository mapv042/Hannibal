"""Public .ics of a cita (no auth: the patient opens it from a WhatsApp button)."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends
from fastapi.responses import PlainTextResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db
from app.core.exceptions import NotFoundError
from app.core.security import verify_link_value
from app.db.models import Appointment, Office
from app.modules.ai.tool_helpers import resolve_active_appointment
from app.modules.scheduling.calendar_file import CALENDAR_LINK_PURPOSE, build_ics, chain_root

router = APIRouter(tags=["Calendar file"])


@router.get("/{appointment_id}/{signature}/cita.ics")
async def appointment_calendar_file(
    appointment_id: UUID,
    signature: str,
    db: AsyncSession = Depends(get_db),
):
    # A bad signature and a missing cita answer the same, so ids can't be probed.
    if not verify_link_value(CALENDAR_LINK_PURPOSE, str(appointment_id), signature):
        raise NotFoundError("Appointment not found")
    appointment = await db.get(Appointment, appointment_id)
    if appointment is None:
        raise NotFoundError("Appointment not found")

    # An old link (the cita moved since) serves where the cita is now.
    live = await resolve_active_appointment(db, appointment)
    if live is None or live.office_id != appointment.office_id:
        return PlainTextResponse("Esta cita fue cancelada.", status_code=410)
    office = await db.get(Office, live.office_id)
    if office is None:
        raise NotFoundError("Appointment not found")

    uid, moves = await chain_root(db, live)
    return Response(
        content=build_ics(live, office, uid=uid, sequence=moves),
        media_type="text/calendar; charset=utf-8",
        headers={
            "Content-Disposition": 'attachment; filename="cita.ics"',
            # The cita can move; a cached copy would add the old time.
            "Cache-Control": "no-store",
        },
    )
