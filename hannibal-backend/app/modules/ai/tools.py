"""Tool definitions and executor for LLM tool-use based conversation."""

from __future__ import annotations

import uuid
from datetime import datetime, time
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import ArrivalStatus, DAYS_ES, MX_TIMEZONE
from app.db.models import Appointment, Office, Patient
from app.modules.ai.tool_helpers import (
    appointment_access_error,
    availability_for_dates,
    format_appointment_dt,
    localize_mx,
    parse_requested_dates,
    resolve_appointment_duration,
)
from app.modules.google_calendar.service import update_event_color
from app.modules.google_calendar.sync import cancel_appointment_in_calendar
from app.modules.scheduling.availability import invalidate_availability_cache
from app.modules.scheduling.booking import book_appointment
from app.modules.scheduling.reschedule_notify import (
    find_pending_doctor_cancellation,
    link_pending_doctor_cancellation,
)
from app.modules.scheduling.tasks import (
    enqueue_abandoned_reschedule_notification,
    enqueue_reschedule_notification,
)
from app.modules.notifications.tasks import (
    enqueue_appointment_notification,
    enqueue_cancellation_notification,
)
from app.modules.audit.tasks import enqueue_write_audit
from app.utils.logger import get_logger
from app.utils.phone import (
    display_or_raw,
    normalize_phone,
    phone_core_digits,
    phone_match_variants,
    to_whatsapp_id,
)

logger = get_logger(__name__)

# An ETA beyond this isn't "on my way", it's a reschedule — don't record it as
# a waiting-room state the doctor might act on.
MAX_ARRIVAL_ETA_MINUTES = 90


# ---------------------------------------------------------------------------
# Tool definitions (Anthropic format — OpenAIService converts automatically)
# ---------------------------------------------------------------------------

TOOL_DEFINITIONS = [
    {
        "name": "get_available_slots",
        "description": (
            "Consulta los horarios disponibles para agendar una cita en una o varias fechas "
            "(máximo 7 por llamada). Usa esta herramienta cuando el paciente quiera saber qué "
            "horarios hay disponibles o cuando necesites verificar disponibilidad antes de "
            "agendar. Si el paciente pregunta algo abierto ('¿qué día tienes espacio?'), "
            "consulta varios días en una sola llamada. Si dice 'mañana', un día de la semana, "
            "o una fecha, calcula la(s) fecha(s) en formato YYYY-MM-DD antes de llamar."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "dates": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Fechas a consultar en formato YYYY-MM-DD (1 a 7).",
                },
            },
            "required": ["dates"],
        },
    },
    {
        "name": "get_patient_appointments",
        "description": (
            "Obtiene las citas próximas del paciente. Usa esta herramienta cuando el paciente "
            "quiera cancelar, reagendar, confirmar asistencia, o preguntar sobre sus citas. "
            "No requiere parámetros — el paciente se identifica automáticamente."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "create_appointment",
        "description": (
            "Crea una nueva cita. Llámala una vez que el paciente confirme un resumen con los datos "
            "de la cita (nombre, fecha, hora, motivo). Al crearla, la cita queda agendada y lista. "
            "No la llames sin esa confirmación de los datos de la cita. "
            "La cita es para quien escribe, a menos que se indique patient_phone: en ese caso la cita "
            "se agenda a nombre de esa otra persona (familiar/tercero), buscándola por teléfono y "
            "registrándola automáticamente si aún no existe."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "patient_name": {
                    "type": "string",
                    "description": (
                        "Nombre completo de la persona que será atendida. Si la cita es para un "
                        "familiar/tercero, es el nombre de ese familiar, no el de quien escribe."
                    ),
                },
                "date": {
                    "type": "string",
                    "description": "Fecha en formato YYYY-MM-DD.",
                },
                "time": {
                    "type": "string",
                    "description": "Hora en formato HH:MM (24 horas).",
                },
                "reason": {
                    "type": "string",
                    "description": "Motivo de la consulta.",
                },
                "patient_phone": {
                    "type": "string",
                    "description": (
                        "Teléfono de contacto (10 dígitos) de la persona que será atendida. "
                        "Pídelo siempre. Si la cita es para un familiar/tercero, es el teléfono de "
                        "esa persona, no el de quien escribe."
                    ),
                },
                "confirm_second_same_day": {
                    "type": "boolean",
                    "description": (
                        "Usa true SOLO cuando el paciente ya fue avisado de que tiene otra cita "
                        "ese mismo día y confirmó que aun así quiere una segunda."
                    ),
                },
            },
            "required": ["patient_name", "patient_phone", "date", "time", "reason"],
        },
    },
    {
        "name": "cancel_appointment",
        "description": (
            "Cancela una cita existente. El paciente debe haber identificado cuál cita "
            "cancelar y proporcionado un motivo de cancelación."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "appointment_id": {
                    "type": "string",
                    "description": "ID de la cita a cancelar (obtenido de get_patient_appointments).",
                },
                "reason": {
                    "type": "string",
                    "description": "Motivo de la cancelación proporcionado por el paciente.",
                },
            },
            "required": ["appointment_id", "reason"],
        },
    },
    {
        "name": "reschedule_appointment",
        "description": (
            "Reagenda una cita existente a un nuevo horario. Cancela la cita anterior "
            "y crea una nueva. El paciente debe haber confirmado el nuevo horario."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "appointment_id": {
                    "type": "string",
                    "description": "ID de la cita original a reagendar.",
                },
                "new_date": {
                    "type": "string",
                    "description": "Nueva fecha en formato YYYY-MM-DD.",
                },
                "new_time": {
                    "type": "string",
                    "description": "Nueva hora en formato HH:MM (24 horas).",
                },
            },
            "required": ["appointment_id", "new_date", "new_time"],
        },
    },
    {
        "name": "confirm_appointment",
        "description": (
            "Registra que el paciente confirma su asistencia, en respuesta a una solicitud de "
            "confirmación o recordatorio que el consultorio le envió previamente. Una cita recién "
            "agendada ya queda lista y no necesita este paso."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "appointment_id": {
                    "type": "string",
                    "description": "ID de la cita a confirmar.",
                },
            },
            "required": ["appointment_id"],
        },
    },
    {
        "name": "report_arrival",
        "description": (
            "Registra si el paciente ya llegó al consultorio o viene en camino, en respuesta al "
            "mensaje que le enviamos a la hora de su cita. El doctor recibe el aviso de inmediato. "
            "Úsala solo cuando haya una LLEGADA PENDIENTE; no la uses para citas futuras."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "appointment_id": {
                    "type": "string",
                    "description": "ID de la cita, tomado del bloque LLEGADA PENDIENTE.",
                },
                "status": {
                    "type": "string",
                    "enum": ["arrived", "on_the_way"],
                    "description": (
                        "arrived si el paciente ya está en el consultorio; on_the_way si "
                        "todavía viene en camino."
                    ),
                },
                "eta_minutes": {
                    "type": "integer",
                    "description": (
                        "Minutos que el paciente dice que tardará en llegar. Solo cuando lo "
                        "diga; no lo estimes tú."
                    ),
                },
            },
            "required": ["appointment_id", "status"],
        },
    },
    {
        "name": "request_urgent_appointment",
        "description": (
            "Registra una solicitud de cita URGENTE cuando el paciente expresa que necesita ser "
            "atendido lo antes posible o antes de los horarios disponibles. NO agenda la cita: "
            "avisa al doctor para que la apruebe, porque una urgencia puede requerir sobreagenda y "
            "solo el doctor puede autorizarla. Úsala solo cuando el paciente realmente indique "
            "urgencia; para una cita normal usa create_appointment. Antes de llamarla pregunta el "
            "motivo de la urgencia."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "reason": {
                    "type": "string",
                    "description": "Motivo de la urgencia descrito por el paciente.",
                },
                "patient_name": {
                    "type": "string",
                    "description": "Nombre del paciente, si ya lo conoces.",
                },
                "preferred_date": {
                    "type": "string",
                    "description": "Fecha preferida YYYY-MM-DD, si el paciente indicó una. Omitir si pide 'lo antes posible'.",
                },
                "preferred_time": {
                    "type": "string",
                    "description": "Hora preferida HH:MM (24 horas), si el paciente indicó una.",
                },
            },
            "required": ["reason"],
        },
    },
]


# ---------------------------------------------------------------------------
# Tool execution context
# ---------------------------------------------------------------------------

class ToolContext:
    """Context passed to tool handlers with DB, office, and patient info."""

    def __init__(
        self,
        db: AsyncSession,
        office: Office,
        patient_id: Optional[uuid.UUID],
        whatsapp_id: str,
        redis_client=None,
    ):
        self.db = db
        self.office = office
        self.patient_id = patient_id
        self.whatsapp_id = whatsapp_id
        # Optional: enables slot locking + availability-cache invalidation.
        self.redis_client = redis_client


def _booking_error(error: str) -> dict:
    """Wrap a booking failure for the patient flow: always steer to alternatives."""
    return {
        "error": f"No se pudo agendar: {error}",
        "next_step": (
            "Consulta get_available_slots para esa fecha y ofrécele al "
            "paciente los horarios que sí están disponibles."
        ),
    }


async def _invalidate_avail(ctx, *dates) -> None:
    """Best-effort availability-cache invalidation for the affected dates."""
    if ctx.redis_client is None:
        return
    for d in dates:
        try:
            await invalidate_availability_cache(ctx.office.id, d, ctx.redis_client)
        except Exception as e:
            logger.warning("tool_avail_cache_invalidate_failed", error=str(e))


async def _find_same_day_appointment(
    ctx, patient_id: uuid.UUID, start_dt: datetime
) -> Optional[Appointment]:
    """An active appointment this patient already has on the same MX day, if any.

    Compared on the Mexico City calendar day rather than a UTC range, so an
    evening appointment isn't counted against the following day.
    """
    day = start_dt.astimezone(MX_TIMEZONE).date()
    day_start = datetime.combine(day, time.min, tzinfo=MX_TIMEZONE)
    day_end = datetime.combine(day, time.max, tzinfo=MX_TIMEZONE)

    result = await ctx.db.execute(
        select(Appointment)
        .where(
            (Appointment.office_id == ctx.office.id)
            & (Appointment.patient_id == patient_id)
            & (Appointment.status.in_(["scheduled", "confirmed"]))
            & (Appointment.start_datetime >= day_start)
            & (Appointment.start_datetime <= day_end)
        )
        .order_by(Appointment.start_datetime)
        .limit(1)
    )
    return result.scalars().first()


# ---------------------------------------------------------------------------
# Tool executor (dispatcher)
# ---------------------------------------------------------------------------

_HANDLERS: dict[str, Any] = {}


def _handler(name: str):
    """Decorator to register a tool handler."""
    def decorator(fn):
        _HANDLERS[name] = fn
        return fn
    return decorator


async def execute_tool(
    tool_name: str,
    arguments: dict,
    ctx: ToolContext,
) -> dict:
    """
    Execute a tool by name and return a JSON-serializable result dict.

    Returns an error dict if the tool fails, so the LLM can communicate
    the issue to the patient naturally.
    """
    handler = _HANDLERS.get(tool_name)
    if not handler:
        return {"error": f"Herramienta desconocida: {tool_name}"}

    try:
        return await handler(arguments, ctx)
    except Exception as e:
        # Log the detail for developers; return a generic message so internal
        # errors (DB/driver text, etc.) never reach the patient via the LLM.
        logger.error("tool_execution_error", tool=tool_name, error=str(e), exc_info=True)
        return {"error": "Ocurrió un error al procesar tu solicitud. Intenta de nuevo en un momento."}


# ---------------------------------------------------------------------------
# Individual tool handlers
# ---------------------------------------------------------------------------

@_handler("get_available_slots")
async def _handle_get_available_slots(args: dict, ctx: ToolContext) -> dict:
    dates = parse_requested_dates(args)
    if isinstance(dates, dict):
        return dates
    # Lay the grid out in the slot length this patient's appointment will take,
    # so we never offer a 30-minute gap and then reserve 45 on top of the next
    # appointment.
    duration_min, _ = await resolve_appointment_duration(
        ctx.db, ctx.office, ctx.patient_id
    )
    return await availability_for_dates(
        ctx.office.id, dates, ctx.db, slot_minutes=duration_min
    )


@_handler("get_patient_appointments")
async def _handle_get_patient_appointments(args: dict, ctx: ToolContext) -> dict:
    if not ctx.patient_id:
        return {"appointments": [], "message": "No se encontró registro del paciente."}

    now = datetime.now(tz=MX_TIMEZONE)
    stmt = (
        select(Appointment)
        .where(
            (Appointment.patient_id == ctx.patient_id)
            & (Appointment.office_id == ctx.office.id)
            & (Appointment.status.in_(["scheduled", "confirmed"]))
            & (Appointment.start_datetime >= now)
        )
        .order_by(Appointment.start_datetime)
    )
    result = await ctx.db.execute(stmt)
    appointments = result.scalars().all()

    if not appointments:
        return {"appointments": [], "message": "El paciente no tiene citas próximas."}

    appt_list = []
    for appt in appointments:
        dt = localize_mx(appt.start_datetime)
        appt_list.append({
            "id": str(appt.id),
            "date": dt.strftime("%Y-%m-%d"),
            "time": dt.strftime("%H:%M"),
            "day_name": DAYS_ES[dt.weekday()],
            "formatted": format_appointment_dt(appt.start_datetime),
            "reason": appt.consultation_reason or "Consulta",
            "status": appt.status,
        })

    return {"appointments": appt_list}


@_handler("create_appointment")
async def _handle_create_appointment(args: dict, ctx: ToolContext) -> dict:
    patient_name = args.get("patient_name", "").strip()
    date_str = args.get("date", "")
    time_str = args.get("time", "")
    reason = args.get("reason", "Consulta")
    patient_phone = (args.get("patient_phone") or "").strip()

    if not all([patient_name, patient_phone, date_str, time_str, reason]):
        return {"error": "Faltan datos para crear la cita. Se requiere: nombre, teléfono, fecha, hora y motivo."}

    try:
        start_dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M").replace(tzinfo=MX_TIMEZONE)
    except ValueError:
        return {"error": f"Fecha u hora inválida: {date_str} {time_str}"}

    # Is this booking for a third party (a family member), or for whoever writes?
    # It's third-party only when a phone is given that differs from the writer's own.
    try:
        writer_core = phone_core_digits(ctx.whatsapp_id)
    except ValueError:
        writer_core = None

    booking_for_third_party = False
    if patient_phone:
        try:
            booking_for_third_party = phone_core_digits(patient_phone) != writer_core
        except ValueError:
            return {
                "error": (
                    f"El teléfono '{patient_phone}' no es válido. Pídele al paciente un número "
                    "de 10 dígitos."
                )
            }

    is_new_patient = False
    if booking_for_third_party:
        # Resolve the third party by phone; register them if not found.
        variants = phone_match_variants(patient_phone)
        result = await ctx.db.execute(
            select(Patient).where(
                (Patient.office_id == ctx.office.id)
                & (
                    Patient.whatsapp_id.in_(variants)
                    | Patient.phone.in_(variants)
                )
            ).limit(1)
        )
        patient = result.scalars().first()
        if not patient:
            patient = Patient(
                id=uuid.uuid4(),
                office_id=ctx.office.id,
                whatsapp_id=to_whatsapp_id(patient_phone),
                phone=normalize_phone(patient_phone),
                name=patient_name,
            )
            ctx.db.add(patient)
            await ctx.db.flush()
            is_new_patient = True
        elif not patient.name:
            patient.name = patient_name
        # Do NOT touch ctx.patient_id: the session still belongs to the writer.
    else:
        # Booking for whoever is writing — use (or create) their own record.
        # patient_phone is the contact number they gave (already validated above);
        # store it normalized. whatsapp_id stays the raw Meta id (used to match
        # incoming messages).
        contact_phone = normalize_phone(patient_phone)
        patient = None
        if ctx.patient_id:
            patient = await ctx.db.get(Patient, ctx.patient_id)
        if not patient:
            patient = Patient(
                id=uuid.uuid4(),
                office_id=ctx.office.id,
                whatsapp_id=ctx.whatsapp_id,
                phone=contact_phone,
                name=patient_name,
            )
            ctx.db.add(patient)
            await ctx.db.flush()
            ctx.patient_id = patient.id
            is_new_patient = True
        else:
            patient.phone = contact_phone
            if not patient.name:
                patient.name = patient_name

    # Same patient, same day: could be a second appointment they really want, or
    # the patient forgetting they already have one. The model can't tell, and
    # booking silently is the wrong guess — hand back the existing appointment
    # and let it ask.
    same_day = (
        None
        if args.get("confirm_second_same_day")
        else await _find_same_day_appointment(ctx, patient.id, start_dt)
    )
    if same_day is not None:
        return {
            "existing_appointment": {
                "appointment_id": str(same_day.id),
                "formatted": format_appointment_dt(same_day.start_datetime),
                "status": same_day.status,
            },
            "next_step": (
                "Este paciente ya tiene una cita ese mismo día. Antes de agendar, "
                "pregúntale si quiere mover la que ya tiene (reschedule_appointment) "
                "o si de verdad necesita una segunda cita el mismo día — no lo asumas. "
                "Si confirma que quiere las dos, vuelve a llamar create_appointment "
                "con confirm_second_same_day=true."
            ),
        }

    # Duration and type from the shared resolver — the same one that laid out
    # the slots this patient was offered.
    duration_min, appt_type = await resolve_appointment_duration(
        ctx.db, ctx.office, patient.id
    )

    outcome = await book_appointment(
        ctx.db,
        ctx.office,
        patient_id=patient.id,
        start_dt=start_dt,
        duration_min=duration_min,
        reason=reason,
        appt_type=appt_type,
        gcal_title=f"Cita: {patient_name}",
        gcal_description=(
            f"Motivo: {reason}\n"
            f"Teléfono: {display_or_raw(patient.phone)}\n"
            f"Agendada por WhatsApp"
        ),
        redis_client=ctx.redis_client,
        booked_by_patient_id=ctx.patient_id,
    )
    if outcome.error:
        return _booking_error(outcome.error)
    appointment = outcome.appointment

    # If this booking answers a slot the doctor cancelled, report back to the
    # doctor via the reschedule notice (which already covers the event); otherwise
    # send the configurable new-appointment / new-patient notification.
    if await link_pending_doctor_cancellation(ctx.db, appointment):
        enqueue_reschedule_notification(appointment.id)
    else:
        enqueue_appointment_notification(appointment.id, is_new_patient)

    # Rule 12: check afterwards that the booking really landed where we told the
    # patient it did — including the Google Calendar event, whose failure
    # book_appointment deliberately swallows.
    enqueue_write_audit(
        appointment.id,
        "book",
        start_datetime=start_dt,
        status="scheduled",
        patient_id=patient.id,
    )

    day_name = DAYS_ES[start_dt.weekday()]
    logger.info("tool_appointment_created", appointment_id=str(appointment.id), office_id=str(ctx.office.id))

    return {
        "success": True,
        "appointment_id": str(appointment.id),
        "patient_name": patient_name,
        "date": date_str,
        "time": time_str,
        "day_name": day_name,
        "formatted_date": f"{day_name} {start_dt.strftime('%d/%m/%Y')}",
        "reason": reason,
        "duration_minutes": duration_min,
        "office_name": ctx.office.name,
        "office_address": ctx.office.address or "",
    }


@_handler("cancel_appointment")
async def _handle_cancel_appointment(args: dict, ctx: ToolContext) -> dict:
    appt_id_str = args.get("appointment_id", "")
    reason = args.get("reason", "")

    try:
        appt_id = uuid.UUID(appt_id_str)
    except ValueError:
        return {"error": f"ID de cita inválido: {appt_id_str}"}

    appointment = await ctx.db.get(Appointment, appt_id)
    if not appointment or appointment.office_id != ctx.office.id:
        return {"error": "No se encontró la cita."}

    access_error = appointment_access_error(appointment, ctx)
    if access_error:
        return {"error": access_error}

    if appointment.status == "cancelled":
        return {"error": "La cita ya fue cancelada previamente."}

    # Format before cancelling
    dt = localize_mx(appointment.start_datetime)
    formatted = format_appointment_dt(appointment.start_datetime)

    # Cancel
    appointment.status = "cancelled"
    appointment.cancelled_by = "patient"
    appointment.cancellation_reason = reason

    await _invalidate_avail(ctx, dt.date())

    # Notify the doctor of the patient cancellation (configurable per office).
    enqueue_cancellation_notification(appointment.id)

    # Google Calendar
    try:
        await cancel_appointment_in_calendar(appt_id, ctx.office.id, ctx.db)
    except Exception as e:
        logger.warning("tool_cancel_gcal_failed", error=str(e))

    # Rule 12: a cancellation that leaves the calendar event standing is worse
    # than a failed cancellation — the slot looks taken and the patient thinks
    # they're free.
    enqueue_write_audit(appointment.id, "cancel", status="cancelled")

    # Rule 13: if the doctor had cancelled a cita and asked this patient to
    # rebook, and they cancelled instead, the doctor has to hear how it actually
    # ended — otherwise they keep holding a slot for someone who isn't coming.
    pending = await find_pending_doctor_cancellation(
        ctx.db,
        ctx.office.id,
        appointment.patient_id,
        exclude_appointment_id=appointment.id,
    )
    if pending is not None:
        enqueue_abandoned_reschedule_notification(pending.id)

    logger.info("tool_appointment_cancelled", appointment_id=appt_id_str)

    return {
        "success": True,
        "appointment_id": appt_id_str,
        "formatted": formatted,
        "reason": reason,
    }


@_handler("reschedule_appointment")
async def _handle_reschedule_appointment(args: dict, ctx: ToolContext) -> dict:
    appt_id_str = args.get("appointment_id", "")
    new_date = args.get("new_date", "")
    new_time = args.get("new_time", "")

    try:
        appt_id = uuid.UUID(appt_id_str)
    except ValueError:
        return {"error": f"ID de cita inválido: {appt_id_str}"}

    appointment = await ctx.db.get(Appointment, appt_id)
    if not appointment or appointment.office_id != ctx.office.id:
        return {"error": "No se encontró la cita."}

    access_error = appointment_access_error(appointment, ctx)
    if access_error:
        return {"error": access_error}

    if appointment.status == "cancelled":
        return {"error": "La cita ya fue cancelada y no puede reagendarse. Ofrece agendar una nueva."}

    try:
        new_start = datetime.strptime(f"{new_date} {new_time}", "%Y-%m-%d %H:%M").replace(tzinfo=MX_TIMEZONE)
    except ValueError:
        return {"error": f"Fecha u hora inválida: {new_date} {new_time}"}

    old_formatted = format_appointment_dt(appointment.start_datetime)
    old_date = localize_mx(appointment.start_datetime).date()
    reason = appointment.consultation_reason or "Consulta"

    patient_name = ""
    patient_phone_display = ""
    if appointment.patient_id:
        patient = await ctx.db.get(Patient, appointment.patient_id)
        if patient:
            patient_name = patient.name or ""
            patient_phone_display = display_or_raw(patient.phone) if patient.phone else ""
    phone_line = f"Teléfono: {patient_phone_display}\n" if patient_phone_display else ""

    # Book the new slot first — a conflict leaves the old appointment intact.
    outcome = await book_appointment(
        ctx.db,
        ctx.office,
        patient_id=appointment.patient_id,
        start_dt=new_start,
        duration_min=appointment.duration_minutes or 30,
        reason=reason,
        appt_type=appointment.type,
        gcal_title=f"Cita: {patient_name}",
        gcal_description=f"Motivo: {reason}\n{phone_line}Reagendada por WhatsApp",
        redis_client=ctx.redis_client,
        # Carry the original booker forward: moving an appointment must not
        # strip the parent who booked it of the right to touch it again.
        booked_by_patient_id=appointment.booked_by_patient_id,
    )
    if outcome.error:
        return _booking_error(outcome.error)
    new_appointment = outcome.appointment

    # Cancel old
    appointment.status = "cancelled"
    appointment.cancelled_by = "patient"
    appointment.cancellation_reason = "Reagendada por el paciente"

    try:
        await cancel_appointment_in_calendar(appt_id, ctx.office.id, ctx.db)
    except Exception as e:
        logger.warning("tool_reschedule_cancel_gcal_failed", error=str(e))

    await _invalidate_avail(ctx, old_date)

    # If this booking answers a slot the doctor cancelled, report back to the doctor.
    if await link_pending_doctor_cancellation(ctx.db, new_appointment):
        enqueue_reschedule_notification(new_appointment.id)

    # Rule 12: audit both halves — the new appointment must exist on the
    # calendar and the old one must have stopped occupying its slot.
    enqueue_write_audit(
        new_appointment.id,
        "reschedule",
        start_datetime=new_start,
        status="scheduled",
        patient_id=new_appointment.patient_id,
    )
    enqueue_write_audit(appointment.id, "cancel", status="cancelled")

    new_day_name = DAYS_ES[new_start.weekday()]
    logger.info("tool_appointment_rescheduled", old_id=appt_id_str, new_id=str(new_appointment.id))

    return {
        "success": True,
        "old_appointment_id": appt_id_str,
        "old_formatted": old_formatted,
        "new_appointment_id": str(new_appointment.id),
        "new_date": new_date,
        "new_time": new_time,
        "new_day_name": new_day_name,
        "new_formatted": format_appointment_dt(new_start),
        "reason": reason,
        "patient_name": patient_name,
    }


@_handler("confirm_appointment")
async def _handle_confirm_appointment(args: dict, ctx: ToolContext) -> dict:
    appt_id_str = args.get("appointment_id", "")

    try:
        appt_id = uuid.UUID(appt_id_str)
    except ValueError:
        return {"error": f"ID de cita inválido: {appt_id_str}"}

    appointment = await ctx.db.get(Appointment, appt_id)
    if not appointment or appointment.office_id != ctx.office.id:
        return {"error": "No se encontró la cita."}

    access_error = appointment_access_error(appointment, ctx)
    if access_error:
        return {"error": access_error}

    if appointment.status == "cancelled":
        return {"error": "La cita fue cancelada y no puede confirmarse."}

    appointment.status = "confirmed"

    # Update Google Calendar color
    if appointment.google_event_id:
        try:
            await update_event_color(ctx.office.id, appointment.google_event_id, "10", ctx.db)
        except Exception as e:
            logger.warning("tool_confirm_gcal_color_failed", error=str(e))

    logger.info("tool_appointment_confirmed", appointment_id=appt_id_str)

    return {
        "success": True,
        "appointment_id": appt_id_str,
        "formatted": format_appointment_dt(appointment.start_datetime),
        "office_name": ctx.office.name,
        "office_address": ctx.office.address or "",
    }


@_handler("report_arrival")
async def _handle_report_arrival(args: dict, ctx: ToolContext) -> dict:
    # Local import keeps Celery out of this module's import graph.
    from app.modules.notifications.tasks import enqueue_arrival_notification

    appt_id_str = args.get("appointment_id", "")
    status = args.get("status", "")

    if status not in (ArrivalStatus.ARRIVED.value, ArrivalStatus.ON_THE_WAY.value):
        return {"error": f"Estado de llegada inválido: {status}"}

    try:
        appt_id = uuid.UUID(appt_id_str)
    except ValueError:
        return {"error": f"ID de cita inválido: {appt_id_str}"}

    appointment = await ctx.db.get(Appointment, appt_id)
    if not appointment or appointment.office_id != ctx.office.id:
        return {"error": "No se encontró la cita."}

    access_error = appointment_access_error(appointment, ctx)
    if access_error:
        return {"error": access_error}

    if appointment.status == "cancelled":
        return {"error": "La cita fue cancelada."}

    eta_minutes = args.get("eta_minutes")
    if eta_minutes is not None:
        try:
            eta_minutes = int(eta_minutes)
        except (TypeError, ValueError):
            eta_minutes = None
        else:
            # A patient saying "llego en 3 horas" is rescheduling, not arriving.
            if not 0 < eta_minutes <= MAX_ARRIVAL_ETA_MINUTES:
                eta_minutes = None

    appointment.arrival_status = status
    appointment.arrival_reported_at = datetime.now(MX_TIMEZONE)
    appointment.arrival_eta_minutes = (
        eta_minutes if status == ArrivalStatus.ON_THE_WAY.value else None
    )

    enqueue_arrival_notification(appointment.id)

    logger.info(
        "tool_arrival_reported",
        appointment_id=appt_id_str,
        office_id=str(ctx.office.id),
        arrival_status=status,
        eta_minutes=eta_minutes,
    )

    return {
        "success": True,
        "appointment_id": appt_id_str,
        "status": status,
        "eta_minutes": eta_minutes,
        "office_name": ctx.office.name,
        "doctor_notified": True,
    }


@_handler("request_urgent_appointment")
async def _handle_request_urgent_appointment(args: dict, ctx: ToolContext) -> dict:
    # Local imports avoid pulling Celery into the module import graph.
    from app.modules.urgencies.service import create_urgency_request
    from app.modules.urgencies.tasks import enqueue_urgency_flow

    reason = args.get("reason", "").strip()
    if not reason:
        return {"error": "Necesito el motivo de la urgencia antes de avisar al doctor."}

    patient_name = args.get("patient_name", "").strip()

    # Optional preferred date+time — both required to build a concrete datetime.
    preferred_time = None
    pdate = args.get("preferred_date", "").strip()
    ptime = args.get("preferred_time", "").strip()
    if pdate and ptime:
        try:
            preferred_time = datetime.strptime(f"{pdate} {ptime}", "%Y-%m-%d %H:%M").replace(tzinfo=MX_TIMEZONE)
        except ValueError:
            preferred_time = None

    # Ensure a patient record exists (name may still be unknown — it's nullable).
    patient = None
    if ctx.patient_id:
        patient = await ctx.db.get(Patient, ctx.patient_id)
    if not patient:
        patient = Patient(
            id=uuid.uuid4(),
            office_id=ctx.office.id,
            whatsapp_id=ctx.whatsapp_id,
            phone=ctx.whatsapp_id,
            name=patient_name or None,
        )
        ctx.db.add(patient)
        await ctx.db.flush()
        ctx.patient_id = patient.id
    elif not patient.name and patient_name:
        patient.name = patient_name

    request = await create_urgency_request(
        ctx.db,
        ctx.office.id,
        patient.id,
        ctx.whatsapp_id,
        reason,
        preferred_time,
    )
    enqueue_urgency_flow(request.id)

    logger.info("tool_urgency_requested", request_id=str(request.id), office_id=str(ctx.office.id))
    return {
        "success": True,
        "next_step": (
            "Dile al paciente que estás consultando con el doctor para conseguirle un espacio "
            "urgente y que le avisarás en cuanto el doctor responda. No prometas un horario todavía."
        ),
    }
