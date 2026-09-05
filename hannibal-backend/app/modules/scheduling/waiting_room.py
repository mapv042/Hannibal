"""Today's waiting room: who answered the arrival check-in, and how.

The check-in task (reminders.tasks.send_arrival_check) asks each patient at
their appointment's start time whether they've arrived; report_arrival writes
the answer onto the appointment. This module reads those answers back for the
doctor channel, so the doctor can ask "¿quién está afuera?" and get a real
answer instead of a guess.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import ArrivalStatus, MX_TIMEZONE
from app.db.models import Appointment, Patient

# How long an arrival stays in the doctor's context. Past this the patient has
# either been seen or gone home, and keeping them listed would be misleading.
WAITING_ROOM_LOOKBACK_HOURS = 3


def _describe(appointment: Appointment) -> str:
    """One-line Spanish description of a patient's reported state."""
    if appointment.arrival_status == ArrivalStatus.ARRIVED.value:
        reported = appointment.arrival_reported_at
        if reported is not None:
            local = reported.astimezone(MX_TIMEZONE)
            return f"ya llegó (avisó a las {local.strftime('%H:%M')})"
        return "ya llegó"

    if appointment.arrival_status == ArrivalStatus.ON_THE_WAY.value:
        if appointment.arrival_eta_minutes:
            return f"viene en camino, dijo que llegaba en {appointment.arrival_eta_minutes} minutos"
        return "viene en camino"

    return "no ha contestado si viene"


async def get_waiting_room(office_id: UUID, db: AsyncSession) -> list[dict]:
    """Today's arrival reports, shaped for the doctor system prompt.

    Covers appointments whose start time falls inside the lookback window and
    that the patient has answered about. Appointments already marked completed
    or cancelled drop out — the doctor has moved on from those.
    """
    now = datetime.now(tz=MX_TIMEZONE)
    window_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    earliest = max(
        window_start,
        now - timedelta(hours=WAITING_ROOM_LOOKBACK_HOURS),
    )
    day_end = datetime.combine(now.date(), time.max, tzinfo=MX_TIMEZONE)

    stmt = (
        select(Appointment, Patient.name)
        .join(Patient, Appointment.patient_id == Patient.id)
        .where(
            (Appointment.office_id == office_id)
            & (Appointment.status.in_(["scheduled", "confirmed"]))
            & (Appointment.arrival_status.is_not(None))
            & (Appointment.start_datetime >= earliest)
            & (Appointment.start_datetime <= day_end)
        )
        .order_by(Appointment.start_datetime)
    )
    rows = (await db.execute(stmt)).all()

    return [
        {
            "patient_name": patient_name or "Paciente",
            "slot": appointment.start_datetime.astimezone(MX_TIMEZONE).strftime("%H:%M"),
            "state": _describe(appointment),
        }
        for appointment, patient_name in rows
    ]
