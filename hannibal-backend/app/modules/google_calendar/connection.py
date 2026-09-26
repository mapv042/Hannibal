"""What happens when Google stops accepting an office's calendar credentials.

A doctor who revokes the grant, changes their Google password, or removes the
app leaves the office with a token Google rejects. Before this module, every
availability lookup and every booking then failed ("tuve un problema técnico")
until someone noticed — and nobody told the doctor.

Now, when Google rejects the credentials (GoogleCalendarAuthError — not a
timeout or a 5xx, which stay "try again later"):

- scheduling carries on with the system's own agenda (working hours,
  appointments, time blocks); only the doctor's Google-only events are unseen;
- the doctor is told over WhatsApp, at most once a day, how to reconnect;
- Google isn't retried on every call for a while, so patients don't pay the
  latency of a doomed request per lookup;
- the write audit stops reporting "event missing in Google" per appointment —
  the disconnection notice already covers it;
- on reconnect, the appointments booked meanwhile are written to Google.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional
from uuid import UUID

import redis.asyncio as aioredis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.celery_dispatch import dispatch
from app.utils.logger import get_logger

logger = get_logger(__name__)

# Set while Google rejects the office's credentials; re-set on every rejection,
# so it lapses on its own a day after Google starts accepting them again.
DISCONNECTED_KEY = "gcal_disconnected:{office_id}"
DISCONNECTED_TTL = 86400
# One WhatsApp notice to the doctor per day while disconnected.
ALERTED_KEY = "gcal_disconnect_alerted:{office_id}"
ALERTED_TTL = 86400

# In-process: don't call Google again for this long after a rejection.
_SKIP_WINDOW = timedelta(minutes=10)
_skip_until: dict[UUID, datetime] = {}

DISCONNECT_NOTICE = (
    "Tu Google Calendar se desconectó: Google ya no acepta el permiso que le diste a "
    "ArgosAI. Sigo agendando citas con la agenda del sistema, pero no veo los eventos "
    "que tengas solo en Google, así que podría agendar encima de ellos. Reconéctalo "
    "aquí: {link}\nAl reconectarlo, las citas agendadas mientras tanto se agregarán a "
    "tu calendario."
)


def _now() -> datetime:
    from app.utils.dates import real_now

    return real_now()


def should_skip_google(office_id: UUID) -> bool:
    """True right after a rejection: use the system's agenda without asking Google."""
    until = _skip_until.get(office_id)
    return until is not None and _now() < until


def report_auth_failure(office_id: UUID, error: Exception) -> None:
    """Record that Google rejected this office's credentials. Never raises."""
    first_in_window = not should_skip_google(office_id)
    _skip_until[office_id] = _now() + _SKIP_WINDOW
    logger.warning(
        "google_calendar_auth_rejected", office_id=str(office_id), error=str(error)
    )
    if first_in_window:
        from app.modules.google_calendar.tasks import handle_calendar_auth_failure

        dispatch(
            handle_calendar_auth_failure,
            [str(office_id)],
            event="gcal_auth_failure_enqueued",
            office_id=str(office_id),
        )


def clear_local_skip(office_id: UUID) -> None:
    _skip_until.pop(office_id, None)


async def is_disconnected(redis_client: aioredis.Redis, office_id: UUID) -> bool:
    try:
        return bool(await redis_client.get(DISCONNECTED_KEY.format(office_id=office_id)))
    except Exception:
        return False


def reconnect_link() -> str:
    base = (settings.frontend_url or "").rstrip("/")
    return f"{base}/dashboard/settings" if base else "el panel de ArgosAI (Configuración)"


async def mark_disconnected_and_notify(
    db: AsyncSession, redis_client: aioredis.Redis, meta_client, office_id: UUID
) -> str:
    """Set the disconnected flag and tell the doctor (once a day). Returns the alert status."""
    from app.db.models import Office
    from app.modules.reminders.wa_templates import (
        TEMPLATE_DOCTOR_CALENDAR_DISCONNECTED,
        build_doctor_calendar_disconnected_params,
    )
    from app.modules.whatsapp.doctor_notify import send_doctor_alert

    await redis_client.setex(DISCONNECTED_KEY.format(office_id=office_id), DISCONNECTED_TTL, "1")
    first = await redis_client.set(
        ALERTED_KEY.format(office_id=office_id), "1", nx=True, ex=ALERTED_TTL
    )
    if not first:
        return "already_alerted"

    office = await db.get(Office, office_id)
    if office is None:
        return "skipped"
    link = reconnect_link()
    return await send_doctor_alert(
        redis_client,
        meta_client,
        office,
        text=DISCONNECT_NOTICE.format(link=link),
        template_name=TEMPLATE_DOCTOR_CALENDAR_DISCONNECTED,
        template_params=build_doctor_calendar_disconnected_params(link),
        log_event="doctor_calendar_disconnected",
    )


async def mark_reconnected(redis_client: aioredis.Redis, office_id: UUID) -> None:
    """Called after the doctor reconnects: clear the flags."""
    clear_local_skip(office_id)
    for key in (DISCONNECTED_KEY, ALERTED_KEY):
        try:
            await redis_client.delete(key.format(office_id=office_id))
        except Exception as e:
            logger.warning("gcal_reconnect_flag_clear_failed", error=str(e))


async def backfill_missing_events(db: AsyncSession, office_id: UUID) -> dict:
    """Write to Google the upcoming appointments that have no event yet.

    These are the citas booked while the calendar was disconnected. Only
    future scheduled/confirmed ones: the past doesn't need to reach the
    doctor's calendar retroactively.
    """
    from app.db.models import Appointment, Patient
    from app.modules.google_calendar.service import create_calendar_event
    from app.utils.dates import now_mx
    from app.utils.phone import display_or_raw

    rows = (await db.execute(
        select(Appointment, Patient)
        .join(Patient, Patient.id == Appointment.patient_id, isouter=True)
        .where(
            (Appointment.office_id == office_id)
            & (Appointment.google_event_id.is_(None))
            & (Appointment.status.in_(["scheduled", "confirmed"]))
            & (Appointment.start_datetime >= now_mx())
        )
        .order_by(Appointment.start_datetime)
    )).all()

    created = failed = 0
    for appt, patient in rows:
        name = (patient.name if patient else None) or "Paciente"
        phone = f"Teléfono: {display_or_raw(patient.phone)}\n" if patient and patient.phone else ""
        try:
            appt.google_event_id = await create_calendar_event(
                office_id=office_id,
                title=f"Cita: {name}",
                start_time=appt.start_datetime,
                end_time=appt.end_datetime,
                description=(
                    f"Motivo: {appt.consultation_reason or 'Consulta'}\n{phone}"
                    "Agendada mientras Google Calendar estaba desconectado"
                ),
                db=db,
                color_id="10" if appt.status == "confirmed" else "9",
            )
            created += 1
        except Exception as e:
            failed += 1
            logger.warning("gcal_backfill_event_failed", appointment_id=str(appt.id), error=str(e))
    await db.commit()
    logger.info("gcal_backfill_done", office_id=str(office_id), created=created, failed=failed)
    return {"created": created, "failed": failed}
