"""Helpers shared by the patient and doctor tool handlers.

Both flows follow the same standard (see CONVENTIONS.md); the presentation
logic they share — Spanish datetime formatting and the availability payload —
lives here so it can't diverge.
"""

from __future__ import annotations

from datetime import date as date_cls, datetime, timedelta
from typing import Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import DAYS_ES, MX_TIMEZONE
from app.db.models import Appointment, Office
from app.modules.scheduling.availability import compute_day_availability
from app.modules.conversation.state import OfferedSlot
from app.utils.dates import (
    long_date_label,
    now_mx,
    relative_day_label,
    spanish_date_label,
    time_label,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)

# The model shouldn't sweep arbitrarily large ranges in one call.
MAX_DATES_PER_QUERY = 7

# When every requested day is full, how far ahead the tool itself looks for the
# next day with room. Doing this in code instead of asking the model to "suggest
# the nearest day" is what keeps "no hay espacios" from being the last word.
NEXT_AVAILABLE_SEARCH_DAYS = 14

# Canonical slot identifier: 'YYYY-MM-DDTHH:MM' in Mexico City time. Readable
# on purpose — it's copied by the model, and a human reading a trace can check it.
SLOT_ID_FORMAT = "%Y-%m-%dT%H:%M"

PARTS_OF_DAY = ("mañana", "tarde")

# Statuses of a past appointment that make a patient "returning" — they have
# actually been seen (or were due to be) by this office.
_VISITED_STATUSES = ("completed", "confirmed", "scheduled")


async def is_returning_patient(
    db: AsyncSession, office: Office, patient_id: Optional[UUID]
) -> bool:
    """Whether this patient has already had a visit with this office.

    Single definition shared by the prompt ("PACIENTE ACTUAL") and the duration
    resolver. Only appointments that already started count: a first visit
    booked five minutes ago is still a first visit, and treating it as history
    flipped the prompt to "ya ha tenido citas previas" mid-conversation and
    quoted the follow-up price for the same person.
    """
    if patient_id is None:
        return False
    existing = await db.execute(
        select(Appointment.id)
        .where(
            (Appointment.office_id == office.id)
            & (Appointment.patient_id == patient_id)
            & (
                (Appointment.status == "completed")
                | (
                    Appointment.status.in_(_VISITED_STATUSES)
                    & (Appointment.start_datetime < now_mx())
                )
            )
        )
        .limit(1)
    )
    return existing.scalars().first() is not None


async def resolve_appointment_duration(
    db: AsyncSession,
    office: Office,
    patient_id: Optional[UUID],
) -> tuple[int, str]:
    """Duration in minutes and appointment type for this patient's next visit.

    Single source of truth for "first visit or follow-up". The slot grid the
    patient is offered and the slot actually reserved MUST come from the same
    answer: computing them separately let the bot offer a 30-minute slot and
    then book 45 minutes on top of the following appointment.

    A patient we don't know yet (no id) counts as a first visit.
    """
    if await is_returning_patient(db, office, patient_id):
        return office.returning_patient_duration_min, "follow_up"
    return office.new_patient_duration_min, "first_visit"


def appointment_access_error(appointment: Appointment, ctx) -> Optional[str]:
    """Error message when the writer may not act on this appointment, else None.

    The patient tools resolve an appointment by id, and until this check existed
    they only verified the office — so an id belonging to a different patient of
    the same practice could be cancelled, moved or confirmed by anyone who
    guessed it.

    Access is granted to the patient the appointment is for, and to whoever
    booked it (a parent who scheduled for their child keeps control of it).
    Appointments created before booked_by_patient_id existed have it NULL and
    fall back to the titular patient alone.

    The message is deliberately identical to the not-found one: a distinct
    "that appointment isn't yours" would confirm the id is real.
    """
    if ctx.patient_id is None:
        return "No se encontró la cita."
    if appointment.patient_id == ctx.patient_id:
        return None
    if appointment.booked_by_patient_id == ctx.patient_id:
        return None
    logger.warning(
        "appointment_access_denied",
        appointment_id=str(appointment.id),
        office_id=str(appointment.office_id),
        requester_patient_id=str(ctx.patient_id),
    )
    return "No se encontró la cita."


def localize_mx(dt: datetime) -> datetime:
    """Normalize a DB datetime (naive or aware) to Mexico City time."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=MX_TIMEZONE)
    return dt.astimezone(MX_TIMEZONE)


def format_appointment_dt(dt: datetime) -> str:
    """Spanish human-readable appointment datetime: 'lunes 6 de julio a las 10:00 AM'.

    The same wording everywhere — tool results, prompt state, patient notices —
    so the model never has to translate one form into another.
    """
    local = localize_mx(dt)
    return f"{long_date_label(local.date())} a las {time_label(local)}"


def slot_id_for(dt: datetime) -> str:
    """Canonical slot id for a datetime (Mexico City wall time)."""
    return localize_mx(dt).strftime(SLOT_ID_FORMAT)


def parse_slot_id(slot_id: str) -> datetime | dict:
    """Parse a slot id into an aware Mexico City datetime, or an error dict."""
    try:
        return datetime.strptime((slot_id or "").strip(), SLOT_ID_FORMAT).replace(
            tzinfo=MX_TIMEZONE
        )
    except ValueError:
        return {
            "error": (
                f"slot_id inválido: '{slot_id}'. Usa el slot_id exacto que devolvió "
                "get_available_slots (formato YYYY-MM-DDTHH:MM)."
            )
        }


def offered_slots_from(result: dict) -> list[OfferedSlot]:
    """The slots an availability payload offered, for ConversationState."""
    days = list(result.get("days") or [])
    if result.get("next_available"):
        days.append(result["next_available"])
    out: list[OfferedSlot] = []
    for day in days:
        for slot in day.get("slots") or []:
            out.append(
                OfferedSlot(
                    slot_id=slot["slot_id"],
                    date_label=day["date_label"],
                    time_label=slot["label"],
                )
            )
    return out


def resolve_requested_days(args: dict) -> tuple[list[str], Optional[str], Optional[dict]]:
    """Dates to look up, from the patient's words (`when`) or exact `dates`.

    Returns (dates, part_of_day, early_result). `early_result` is set when the
    tool must answer without looking anything up: the words can't be read, or
    they have two readings — then the model gets both options to ask about,
    never a guess (see ai/date_expressions.py).
    """
    from app.modules.ai.date_expressions import resolve_day_expression

    part_of_day = args.get("part_of_day")
    when = (args.get("when") or "").strip()
    if not when:
        dates = parse_requested_dates(args)
        if isinstance(dates, dict):
            return [], part_of_day, dates
        return dates, part_of_day, None

    today = now_mx().date()
    resolution = resolve_day_expression(when, today)
    if resolution is None:
        return [], part_of_day, {
            "error": f"No pude interpretar «{when}» como un día.",
            "next_step": (
                "Pregúntale al paciente qué día quiere. Si ya tienes la fecha exacta, "
                "pásala en dates (YYYY-MM-DD)."
            ),
        }
    if resolution.ambiguous:
        return [], part_of_day, {
            "ambiguous_date": when,
            "options": [
                {"date": d.isoformat(), "date_label": long_date_label(d, today)}
                for d in resolution.dates
            ],
            "reason": resolution.note,
            "next_step": (
                "Lo que dijo el paciente tiene más de una lectura. Pregúntale cuál de estas "
                "fechas quiso decir — no la elijas tú."
            ),
        }
    return (
        [d.isoformat() for d in resolution.dates][:MAX_DATES_PER_QUERY],
        part_of_day or resolution.part_of_day,
        None,
    )


def parse_requested_dates(args: dict) -> list[str] | dict:
    """Extract the requested date list from tool args.

    Accepts the current `dates` array or the legacy single `date` string.
    Returns the list, or an `{"error": ...}` dict for the model to relay.
    """
    dates = args.get("dates")
    if not dates:
        single = args.get("date", "")
        dates = [single] if single else []
    if not dates:
        return {"error": "Falta la fecha. Indica una o varias fechas en formato YYYY-MM-DD."}
    if len(dates) > MAX_DATES_PER_QUERY:
        return {
            "error": (
                f"Máximo {MAX_DATES_PER_QUERY} fechas por consulta. "
                "Consulta primero los días más probables."
            )
        }
    return list(dates)


class CalendarUnavailable(Exception):
    """The availability engine could not read the doctor's calendar."""


async def _day_payload(
    office_id: UUID,
    target_date: date_cls,
    today: date_cls,
    db: AsyncSession,
    slot_minutes: Optional[int],
    part_of_day: Optional[str],
) -> dict:
    """One day's availability, in the shape both flows' tools return."""
    date_label = long_date_label(target_date, today)
    base = {
        "date": target_date.isoformat(),
        "date_label": date_label,
        "relative_day": relative_day_label(target_date, today),
    }
    try:
        result = await compute_day_availability(
            office_id, target_date, db,
            slot_minutes=slot_minutes,
            only_future=True,
        )
    except Exception as e:
        logger.warning(
            "tool_availability_failed", error=str(e), date=target_date.isoformat()
        )
        raise CalendarUnavailable(str(e)) from e

    if not result.has_schedule:
        return {
            **base,
            "slots": [],
            "message": f"El consultorio no atiende el {date_label}.",
        }

    slots = [
        {
            "slot_id": s.start_time.astimezone(MX_TIMEZONE).strftime(SLOT_ID_FORMAT),
            "label": time_label(s.start_time.astimezone(MX_TIMEZONE)),
            "period": "mañana" if s.start_time.astimezone(MX_TIMEZONE).hour < 12 else "tarde",
        }
        for s in result.slots
    ]
    if part_of_day in PARTS_OF_DAY:
        slots = [s for s in slots if s["period"] == part_of_day]

    if not slots:
        qualifier = f" por la {part_of_day}" if part_of_day in PARTS_OF_DAY else ""
        message = f"No quedan horarios libres{qualifier} el {date_label}."
    else:
        message = f"{len(slots)} horarios libres el {date_label}."
    return {**base, "slots": slots, "message": message}


async def slots_on_day(
    office_id: UUID,
    target_date: date_cls,
    db: AsyncSession,
    *,
    slot_minutes: Optional[int] = None,
) -> list[dict]:
    """The bookable slots of one day, in the tools' {slot_id, label, period} shape.

    What get_available_slots offers and what prepare_booking accepts are the
    same list by construction. Raises CalendarUnavailable on a calendar failure.
    """
    today = now_mx().date()
    day = await _day_payload(office_id, target_date, today, db, slot_minutes, None)
    return day["slots"]


async def availability_for_dates(
    office_id: UUID,
    dates: list[str],
    db: AsyncSession,
    *,
    slot_minutes: Optional[int] = None,
    part_of_day: Optional[str] = None,
) -> dict:
    """Availability payload for one or several dates (shared by both flows).

    Returns `{"days": [...]}` where each slot carries a `slot_id` (the exact
    value to book with) and a 12-hour `label` (the exact text to show). The
    model copies both and converts neither.

    When no requested day has room, the tool itself searches forward (up to
    NEXT_AVAILABLE_SEARCH_DAYS) and adds `next_available`, so a full day ends in
    an alternative rather than a dead end.

    A calendar failure is reported as `error_kind: "calendar_unavailable"`,
    never as an empty day: "I couldn't check" and "there's no room" are
    different answers, and conflating them produced false "no hay espacios".

    Args:
        slot_minutes: lay the grid out in slots of this length — pass the
            duration the appointment will actually take (see
            resolve_appointment_duration) so what's offered is what's booked.
            None keeps each schedule's configured duration.
        part_of_day: "mañana" or "tarde" to keep only that half of the day.
    """
    today = now_mx().date()
    parsed: list[date_cls] = []
    for date_str in dates:
        try:
            parsed.append(date_cls.fromisoformat(str(date_str).strip()))
        except ValueError:
            return {"error": f"Fecha inválida: {date_str}. Usa formato YYYY-MM-DD."}

    past = [d for d in parsed if d < today]
    if past and len(past) == len(parsed):
        return {
            "error": (
                f"Esa fecha ya pasó (hoy es {long_date_label(today, today)}). "
                "Revisa en el CALENDARIO DE REFERENCIA la fecha que quiso decir el paciente."
            )
        }

    days: list[dict] = []
    try:
        for target_date in parsed:
            if target_date < today:
                continue
            days.append(
                await _day_payload(office_id, target_date, today, db, slot_minutes, part_of_day)
            )

        payload: dict = {"days": days}
        if not any(d["slots"] for d in days):
            cursor = max(parsed) + timedelta(days=1)
            for _ in range(NEXT_AVAILABLE_SEARCH_DAYS):
                day = await _day_payload(office_id, cursor, today, db, slot_minutes, part_of_day)
                if day["slots"]:
                    payload["next_available"] = day
                    break
                cursor += timedelta(days=1)
            else:
                payload["message"] = (
                    f"No hay horarios libres en los próximos {NEXT_AVAILABLE_SEARCH_DAYS} "
                    "días después de las fechas consultadas."
                )
    except CalendarUnavailable:
        return {
            "error": (
                "No pude consultar la agenda del doctor en este momento (falla técnica, "
                "no falta de espacio)."
            ),
            "error_kind": "calendar_unavailable",
            "next_step": (
                "Dile al paciente que tuviste un problema técnico al revisar la agenda y que "
                "lo intente en unos minutos. No le digas que no hay espacios."
            ),
        }

    return payload


async def resolve_active_appointment(
    db: AsyncSession, appointment: Appointment
) -> Optional[Appointment]:
    """Follow a reschedule chain forward to the appointment that is live now.

    A reschedule cancels one row and creates another, so an id the model picked
    up earlier in the turn goes stale the moment the appointment moves. Without
    this, asking to cancel right after rescheduling hit "esa cita ya fue
    cancelada", and the model recovered by re-reading and trying again — which
    read to the patient as the assistant failing and then contradicting itself.

    Returns the live appointment (possibly the one passed in), or None when the
    chain ends in a cancellation that nothing replaced.
    """
    current = appointment
    seen = {current.id}

    while current.status == "cancelled":
        successor = (
            await db.execute(
                select(Appointment)
                .where(Appointment.rescheduled_from == current.id)
                .order_by(Appointment.created_at.desc())
                .limit(1)
            )
        ).scalars().first()
        if successor is None or successor.id in seen:
            return None
        seen.add(successor.id)
        current = successor

    return current
