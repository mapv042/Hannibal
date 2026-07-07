"""Helpers shared by the patient and doctor tool handlers.

Both flows follow the same standard (see CONVENTIONS.md); the presentation
logic they share — Spanish datetime formatting and the availability payload —
lives here so it can't diverge.
"""

from __future__ import annotations

from datetime import date as date_cls, datetime
from typing import Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import DAYS_ES, MX_TIMEZONE
from app.modules.scheduling.availability import compute_day_availability
from app.utils.dates import relative_day_label, spanish_date_label
from app.utils.logger import get_logger

logger = get_logger(__name__)

# The model shouldn't sweep arbitrarily large ranges in one call.
MAX_DATES_PER_QUERY = 7


def localize_mx(dt: datetime) -> datetime:
    """Normalize a DB datetime (naive or aware) to Mexico City time."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=MX_TIMEZONE)
    return dt.astimezone(MX_TIMEZONE)


def format_appointment_dt(dt: datetime) -> str:
    """Spanish human-readable appointment datetime: 'lunes 06/07/2026 a las 10:00'."""
    local = localize_mx(dt)
    return f"{DAYS_ES[local.weekday()]} {local.strftime('%d/%m/%Y')} a las {local.strftime('%H:%M')}"


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


async def availability_for_dates(
    office_id: UUID,
    dates: list[str],
    db: AsyncSession,
) -> dict:
    """Availability payload for one or several dates (shared by both flows).

    Per day: date, day_name, relative_day, slots and a Spanish message. Dates
    are grounded relative to today so the model never treats "mañana" and its
    absolute date as two different days.
    """
    today = datetime.now(tz=MX_TIMEZONE).date()
    days: list[dict] = []

    for date_str in dates:
        try:
            target_date = date_cls.fromisoformat(date_str)
        except ValueError:
            return {"error": f"Fecha inválida: {date_str}. Usa formato YYYY-MM-DD."}

        relative_day = relative_day_label(target_date, today)
        date_label = spanish_date_label(target_date, today)
        day_name = DAYS_ES[target_date.weekday()]

        try:
            result = await compute_day_availability(
                office_id, target_date, db, only_future=True,
            )
        except Exception as e:
            logger.warning("tool_availability_failed", error=str(e), date=date_str)
            return {
                "error": (
                    "No se pudo consultar la disponibilidad del calendario. "
                    "Intenta de nuevo en unos minutos."
                )
            }

        if not result.has_schedule:
            days.append({
                "date": date_str,
                "day_name": day_name,
                "relative_day": relative_day,
                "slots": [],
                "message": f"No hay horario de atención configurado para {date_label}.",
            })
            continue

        slots = [
            {
                "time": s.start_time.strftime("%H:%M"),
                "period": "mañana" if s.start_time.hour < 12 else "tarde",
            }
            for s in result.slots
        ]
        days.append({
            "date": date_str,
            "day_name": day_name,
            "relative_day": relative_day,
            "slots": slots,
            "message": f"{'No hay' if not slots else str(len(slots))} horarios disponibles para {date_label}.",
        })

    if len(days) == 1:
        return days[0]
    return {"days": days}
