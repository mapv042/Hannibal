"""Google Calendar writes for appointments, applied only after the commit.

Google can't take part in our transaction. Writing to it while a turn is still
open meant a turn that then failed — a tool that raised (its SAVEPOINT rolls
back), anything later in the turn, the commit itself — left Google ahead of
the database: an event with no cita holding the slot, or a cita still active
in the DB shown "[CANCELADA]" in the doctor's calendar.

So the writers (book_appointment, the reschedule and cancel paths, the urgency
overbook, the dashboard) don't call Google. They `defer()` — note on the DB
session that an appointment's event must be brought in line — and whoever
commits calls `apply_pending()` afterwards. Each pending entry is reconciled
against what actually got committed, never against what the writer intended:

- the row doesn't exist (rolled back)            → nothing;
- active, no event                               → create it (idempotent id);
- active, event, `move` requested                → move it to the row's time;
- cancelled, event                               → mark it "[CANCELADA]" (frees the slot).

That is what makes a rolled-back SAVEPOINT harmless: an entry deferred inside
it finds the row as the rollback left it.

A commit site that forgets `apply_pending()` degrades, it doesn't break: the
hourly backfill creates missing events and the write audit frees the slot of a
cancelled cita.

The write audit (Rule 12) rides the same queue (`defer_audit`): it is
dispatched after the commit, and only for writes that survived. Enqueued inside
the transaction, it audited writes that rolled back — a failed reschedule found
the old cita "scheduled" where the action had said "cancelled" and paged the
doctor about a divergence that wasn't there. A tool call that raises discards
what it queued (`checkpoint` / `restore`, used by execute_tool); a turn that
fails before its commit never reaches `apply_pending`.
"""

from __future__ import annotations

from typing import Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import GoogleCalendarAuthError
from app.utils.logger import get_logger

logger = get_logger(__name__)

_PENDING_KEY = "gcal_pending"
_AUDIT_KEY = "audit_pending"
ACTIVE_STATUSES = ("scheduled", "confirmed")


def defer(
    db: AsyncSession,
    appointment_id: UUID,
    *,
    title: Optional[str] = None,
    description: Optional[str] = None,
    color_id: Optional[str] = None,
    note: Optional[str] = None,
    move: bool = False,
) -> None:
    """Note that this appointment's Google event must follow the row after the commit.

    `title` / `description` / `color_id` shape the event if one is created;
    `note` is appended to it if it ends up marked cancelled; `move` asks for an
    existing event to follow the row's (new) time.
    """
    pending: dict = _pending(db)
    entry = pending.setdefault(str(appointment_id), {})
    for key, value in (("title", title), ("description", description), ("color_id", color_id), ("note", note)):
        if value is not None:
            entry[key] = value
    if move:
        entry["move"] = True


def defer_audit(db: AsyncSession, appointment_id: UUID, action: str, **expectation) -> None:
    """Queue the write audit (audit.tasks.enqueue_write_audit) for after the commit."""
    db.info.setdefault(_AUDIT_KEY, []).append((appointment_id, action, expectation))


def has_pending(db: AsyncSession) -> bool:
    return bool(db.info.get(_PENDING_KEY)) or bool(db.info.get(_AUDIT_KEY))


def checkpoint(db) -> Optional[tuple]:
    """What is queued right now, to roll the queue back with a failed SAVEPOINT."""
    info = getattr(db, "info", None)
    if info is None:
        return None
    return (
        {k: dict(v) for k, v in info.get(_PENDING_KEY, {}).items()},
        len(info.get(_AUDIT_KEY, [])),
    )


def restore(db, saved: Optional[tuple]) -> None:
    """Forget what was queued since `checkpoint` (the writes behind it rolled back)."""
    if saved is None:
        return
    pending, audits = saved
    db.info[_PENDING_KEY] = pending
    if _AUDIT_KEY in db.info:
        del db.info[_AUDIT_KEY][audits:]


async def apply_pending(db: AsyncSession) -> int:
    """Bring Google in line with what was committed. Never raises; returns writes made.

    Call it after a successful commit. Each appointment is committed on its own,
    so one Google failure doesn't undo the event ids already stored.
    """
    pending = db.info.pop(_PENDING_KEY, None) or {}
    audits = db.info.pop(_AUDIT_KEY, None) or []
    writes = 0
    for appointment_id, entry in pending.items():
        try:
            if await _reconcile(db, UUID(appointment_id), entry):
                writes += 1
            await db.commit()
        except Exception as e:
            await db.rollback()
            logger.error(
                "gcal_apply_failed", appointment_id=appointment_id, error=str(e)
            )
    # After the Google writes, so the audit finds the events they created.
    if audits:
        from app.modules.audit.tasks import enqueue_write_audit

        for appointment_id, action, expectation in audits:
            enqueue_write_audit(appointment_id, action, **expectation)
    return writes


def _pending(db: AsyncSession) -> dict:
    return db.info.setdefault(_PENDING_KEY, {})


async def _reconcile(db: AsyncSession, appointment_id: UUID, entry: dict) -> bool:
    from app.db.models import Appointment, Office, Patient
    from app.modules.google_calendar import connection
    from app.modules.google_calendar.connection import create_appointment_event
    from app.modules.google_calendar.service import (
        create_calendar_event,
        calendar_event_id_for,
        mark_event_cancelled,
        update_calendar_event,
    )

    appointment = await db.get(Appointment, appointment_id)
    if appointment is None:
        logger.info("gcal_apply_skipped_rolled_back", appointment_id=str(appointment_id))
        return False
    office = await db.get(Office, appointment.office_id)
    if office is None or not office.google_calendar_token:
        return False
    if connection.should_skip_google(office.id):
        # Credentials just rejected: the reconnect backfills the events.
        return False

    try:
        if appointment.status in ACTIVE_STATUSES:
            if appointment.google_event_id is None:
                if "title" in entry:
                    appointment.google_event_id = await create_calendar_event(
                        office_id=office.id,
                        title=entry["title"],
                        start_time=appointment.start_datetime,
                        end_time=appointment.end_datetime,
                        description=entry.get("description"),
                        db=db,
                        color_id=entry.get("color_id", "9"),
                        event_id=calendar_event_id_for(appointment.id),
                    )
                else:
                    patient = await db.get(Patient, appointment.patient_id)
                    await create_appointment_event(db, appointment, patient, "Agendada por el asistente")
                return True
            if entry.get("move"):
                await update_calendar_event(
                    office_id=office.id,
                    google_event_id=appointment.google_event_id,
                    start_time=appointment.start_datetime,
                    end_time=appointment.end_datetime,
                    db=db,
                )
                return True
            return False

        if appointment.status == "cancelled" and appointment.google_event_id:
            await mark_event_cancelled(
                office_id=office.id,
                google_event_id=appointment.google_event_id,
                db=db,
                note=entry.get("note"),
            )
            return True
        return False
    except GoogleCalendarAuthError as e:
        connection.report_auth_failure(office.id, e)
        raise
