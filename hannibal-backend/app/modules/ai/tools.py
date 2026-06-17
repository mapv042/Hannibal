"""Tool definitions and executor for LLM tool-use based conversation."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, date as date_cls
from typing import Any, Optional
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import DAYS_ES, MX_TIMEZONE
from app.db.models import Appointment, Office, Patient
from app.modules.google_calendar.service import (
    create_calendar_event, update_event_color,
)
from app.modules.google_calendar.sync import cancel_appointment_in_calendar
from app.modules.scheduling.availability import compute_day_availability
from app.modules.scheduling.reschedule_notify import link_pending_doctor_cancellation
from app.modules.scheduling.tasks import enqueue_reschedule_notification
from app.utils.dates import relative_day_label, spanish_date_label
from app.utils.logger import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Tool definitions (Anthropic format — OpenAIService converts automatically)
# ---------------------------------------------------------------------------

TOOL_DEFINITIONS = [
    {
        "name": "get_available_slots",
        "description": (
            "Consulta los horarios disponibles para agendar una cita en una o varias fechas. "
            "Usa esta herramienta cuando el paciente quiera saber qué horarios hay disponibles "
            "o cuando necesites verificar disponibilidad antes de agendar. "
            "Si el paciente dice 'mañana', un día de la semana, o una fecha, calcula la fecha "
            "correcta en formato YYYY-MM-DD antes de llamar."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "date": {
                    "type": "string",
                    "description": "Fecha en formato YYYY-MM-DD.",
                },
            },
            "required": ["date"],
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
            "No la llames sin esa confirmación de los datos de la cita."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "patient_name": {
                    "type": "string",
                    "description": "Nombre completo del paciente.",
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
            },
            "required": ["patient_name", "date", "time", "reason"],
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
    ):
        self.db = db
        self.office = office
        self.patient_id = patient_id
        self.whatsapp_id = whatsapp_id


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
        logger.error("tool_execution_error", tool=tool_name, error=str(e), exc_info=True)
        return {"error": f"Error al ejecutar {tool_name}: {str(e)}"}


# ---------------------------------------------------------------------------
# Individual tool handlers
# ---------------------------------------------------------------------------

@_handler("get_available_slots")
async def _handle_get_available_slots(args: dict, ctx: ToolContext) -> dict:
    date_str = args.get("date", "")
    try:
        target_date = date_cls.fromisoformat(date_str)
    except ValueError:
        return {"error": f"Fecha inválida: {date_str}. Usa formato YYYY-MM-DD."}

    today = datetime.now(tz=MX_TIMEZONE).date()
    # Ground the date relative to today so the model never treats "mañana" and
    # its absolute date ("miércoles 17") as two different days.
    relative_day = relative_day_label(target_date, today)
    date_label = spanish_date_label(target_date, today)
    day_name = DAYS_ES[target_date.weekday()]

    try:
        result = await compute_day_availability(
            ctx.office.id, target_date, ctx.db, only_future=True,
        )
    except Exception as e:
        logger.warning("tool_availability_failed", error=str(e))
        return {"error": "No se pudo consultar la disponibilidad del calendario. Intenta de nuevo en unos minutos."}

    if not result.has_schedule:
        return {
            "date": date_str,
            "day_name": day_name,
            "relative_day": relative_day,
            "slots": [],
            "message": f"No hay horario de atención configurado para {date_label}.",
        }

    slots = [
        {
            "time": s.start_time.strftime("%H:%M"),
            "period": "mañana" if s.start_time.hour < 12 else "tarde",
        }
        for s in result.slots
    ]
    return {
        "date": date_str,
        "day_name": day_name,
        "relative_day": relative_day,
        "slots": slots,
        "message": f"{'No hay' if not slots else str(len(slots))} horarios disponibles para {date_label}.",
    }


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
        dt = appt.start_datetime
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=MX_TIMEZONE)
        else:
            dt = dt.astimezone(MX_TIMEZONE)
        appt_list.append({
            "id": str(appt.id),
            "date": dt.strftime("%Y-%m-%d"),
            "time": dt.strftime("%H:%M"),
            "day_name": DAYS_ES[dt.weekday()],
            "formatted": f"{DAYS_ES[dt.weekday()]} {dt.strftime('%d/%m/%Y')} a las {dt.strftime('%H:%M')}",
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

    if not all([patient_name, date_str, time_str, reason]):
        return {"error": "Faltan datos para crear la cita. Se requiere: nombre, fecha, hora y motivo."}

    try:
        start_dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M").replace(tzinfo=MX_TIMEZONE)
    except ValueError:
        return {"error": f"Fecha u hora inválida: {date_str} {time_str}"}

    # Ensure patient record exists
    patient = None
    if ctx.patient_id:
        patient = await ctx.db.get(Patient, ctx.patient_id)

    if not patient:
        # Create patient
        patient = Patient(
            id=uuid.uuid4(),
            office_id=ctx.office.id,
            whatsapp_id=ctx.whatsapp_id,
            phone=ctx.whatsapp_id,
            name=patient_name,
        )
        ctx.db.add(patient)
        await ctx.db.flush()
        ctx.patient_id = patient.id
    elif not patient.name:
        patient.name = patient_name

    # Determine duration based on patient type (new vs returning)
    existing_appt = await ctx.db.execute(
        select(Appointment).where(
            (Appointment.office_id == ctx.office.id)
            & (Appointment.patient_id == patient.id)
            & (Appointment.status.in_(["completed", "confirmed", "scheduled"]))
        ).limit(1)
    )
    is_returning = existing_appt.scalars().first() is not None
    duration_min = (
        ctx.office.returning_patient_duration_min if is_returning
        else ctx.office.new_patient_duration_min
    )
    appt_type = "follow_up" if is_returning else "first_visit"

    duration = timedelta(minutes=duration_min)
    end_dt = start_dt + duration

    # Google Calendar event
    google_event_id = None
    if ctx.office.google_calendar_token:
        try:
            google_event_id = await create_calendar_event(
                office_id=ctx.office.id,
                title=f"Cita: {patient_name}",
                start_time=start_dt,
                end_time=end_dt,
                description=f"Motivo: {reason}\nAgendada por WhatsApp",
                db=ctx.db,
                color_id="9",
            )
        except Exception as e:
            logger.error("tool_create_gcal_failed", error=str(e))

    # Create appointment
    appointment_id = uuid.uuid4()
    appointment = Appointment(
        id=appointment_id,
        office_id=ctx.office.id,
        patient_id=patient.id,
        start_datetime=start_dt,
        end_datetime=end_dt,
        duration_minutes=duration_min,
        type=appt_type,
        consultation_reason=reason,
        status="scheduled",
        google_event_id=google_event_id,
    )
    ctx.db.add(appointment)
    await ctx.db.flush()

    # If this booking answers a slot the doctor cancelled, report back to the doctor.
    if await link_pending_doctor_cancellation(ctx.db, appointment):
        enqueue_reschedule_notification(appointment.id)

    day_name = DAYS_ES[start_dt.weekday()]
    logger.info("tool_appointment_created", appointment_id=str(appointment_id), office_id=str(ctx.office.id))

    return {
        "success": True,
        "appointment_id": str(appointment_id),
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

    if appointment.status == "cancelled":
        return {"error": "La cita ya fue cancelada previamente."}

    # Format before cancelling
    dt = appointment.start_datetime
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=MX_TIMEZONE)
    else:
        dt = dt.astimezone(MX_TIMEZONE)
    formatted = f"{DAYS_ES[dt.weekday()]} {dt.strftime('%d/%m/%Y')} a las {dt.strftime('%H:%M')}"

    # Cancel
    appointment.status = "cancelled"
    appointment.cancelled_by = "patient"
    appointment.cancellation_reason = reason

    # Google Calendar
    try:
        await cancel_appointment_in_calendar(appt_id, ctx.office.id, ctx.db)
    except Exception as e:
        logger.warning("tool_cancel_gcal_failed", error=str(e))

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

    try:
        new_start = datetime.strptime(f"{new_date} {new_time}", "%Y-%m-%d %H:%M").replace(tzinfo=MX_TIMEZONE)
    except ValueError:
        return {"error": f"Fecha u hora inválida: {new_date} {new_time}"}

    # Format old appointment
    old_dt = appointment.start_datetime
    if old_dt.tzinfo is None:
        old_dt = old_dt.replace(tzinfo=MX_TIMEZONE)
    else:
        old_dt = old_dt.astimezone(MX_TIMEZONE)
    old_formatted = f"{DAYS_ES[old_dt.weekday()]} {old_dt.strftime('%d/%m/%Y')} a las {old_dt.strftime('%H:%M')}"

    # Cancel old
    appointment.status = "cancelled"
    appointment.cancelled_by = "patient"
    appointment.cancellation_reason = "Reagendada por el paciente"

    try:
        await cancel_appointment_in_calendar(appt_id, ctx.office.id, ctx.db)
    except Exception as e:
        logger.warning("tool_reschedule_cancel_gcal_failed", error=str(e))

    # Create new
    patient_name = ""
    if appointment.patient_id:
        patient = await ctx.db.get(Patient, appointment.patient_id)
        if patient:
            patient_name = patient.name or ""

    duration = timedelta(minutes=appointment.duration_minutes or 30)
    new_end = new_start + duration
    reason = appointment.consultation_reason or "Consulta"

    google_event_id = None
    if ctx.office.google_calendar_token:
        try:
            google_event_id = await create_calendar_event(
                office_id=ctx.office.id,
                title=f"Cita: {patient_name}",
                start_time=new_start,
                end_time=new_end,
                description=f"Motivo: {reason}\nReagendada por WhatsApp",
                db=ctx.db,
                color_id="9",
            )
        except Exception as e:
            logger.error("tool_reschedule_gcal_create_failed", error=str(e))

    new_appointment_id = uuid.uuid4()
    new_appointment = Appointment(
        id=new_appointment_id,
        office_id=ctx.office.id,
        patient_id=appointment.patient_id,
        start_datetime=new_start,
        end_datetime=new_end,
        duration_minutes=appointment.duration_minutes or 30,
        consultation_reason=reason,
        status="scheduled",
        google_event_id=google_event_id,
    )
    ctx.db.add(new_appointment)
    await ctx.db.flush()

    # If this booking answers a slot the doctor cancelled, report back to the doctor.
    if await link_pending_doctor_cancellation(ctx.db, new_appointment):
        enqueue_reschedule_notification(new_appointment.id)

    new_day_name = DAYS_ES[new_start.weekday()]
    logger.info("tool_appointment_rescheduled", old_id=appt_id_str, new_id=str(new_appointment_id))

    return {
        "success": True,
        "old_appointment_id": appt_id_str,
        "old_formatted": old_formatted,
        "new_appointment_id": str(new_appointment_id),
        "new_date": new_date,
        "new_time": new_time,
        "new_day_name": new_day_name,
        "new_formatted": f"{new_day_name} {new_start.strftime('%d/%m/%Y')} a las {new_start.strftime('%H:%M')}",
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

    if appointment.status == "cancelled":
        return {"error": "La cita fue cancelada y no puede confirmarse."}

    appointment.status = "confirmed"

    # Update Google Calendar color
    if appointment.google_event_id:
        try:
            await update_event_color(ctx.office.id, appointment.google_event_id, "10", ctx.db)
        except Exception as e:
            logger.warning("tool_confirm_gcal_color_failed", error=str(e))

    dt = appointment.start_datetime
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=MX_TIMEZONE)
    else:
        dt = dt.astimezone(MX_TIMEZONE)

    logger.info("tool_appointment_confirmed", appointment_id=appt_id_str)

    return {
        "success": True,
        "appointment_id": appt_id_str,
        "formatted": f"{DAYS_ES[dt.weekday()]} {dt.strftime('%d/%m/%Y')} a las {dt.strftime('%H:%M')}",
        "office_name": ctx.office.name,
        "office_address": ctx.office.address or "",
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
