"""Tool definitions and handlers for doctor-facing commands."""

from __future__ import annotations

import uuid
from datetime import datetime, date as date_cls, time as time_type
from typing import Any, Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
import redis.asyncio as redis

from app.core.constants import DAYS_ES, MX_TIMEZONE
from app.db.models import Appointment, Office, Patient, TimeBlock
from app.modules.google_calendar.service import update_event_color, update_calendar_event
from app.modules.google_calendar.sync import cancel_appointment_in_calendar, sync_time_block
from app.modules.whatsapp.coexistence import pause_bot, resume_bot, check_pause
from app.modules.whatsapp.meta_client import MetaCloudClient
from app.utils.logger import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Tool definitions (Anthropic format)
# ---------------------------------------------------------------------------

DOCTOR_TOOL_DEFINITIONS = [
    {
        "name": "get_appointments_by_date",
        "description": (
            "Obtiene todas las citas del consultorio para una fecha específica. "
            "Si no se especifica fecha, usa la fecha de hoy."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "date": {
                    "type": "string",
                    "description": "Fecha en formato YYYY-MM-DD. Si no se proporciona, se usa hoy.",
                },
            },
        },
    },
    {
        "name": "cancel_appointment",
        "description": (
            "Cancela una cita. Puede identificarse por ID o por nombre del paciente "
            "y fecha/hora si hay ambigüedad."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "appointment_id": {
                    "type": "string",
                    "description": "ID de la cita a cancelar.",
                },
                "reason": {
                    "type": "string",
                    "description": "Motivo de cancelación (opcional).",
                },
            },
            "required": ["appointment_id"],
        },
    },
    {
        "name": "pause_bot",
        "description": (
            "Pausa el bot para que no responda a pacientes. "
            "Útil cuando el doctor quiere atender directamente por WhatsApp."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "minutes": {
                    "type": "integer",
                    "description": "Minutos de pausa. Por defecto 60.",
                },
            },
        },
    },
    {
        "name": "resume_bot",
        "description": "Reanuda el bot inmediatamente (termina la pausa antes de tiempo).",
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "block_time",
        "description": (
            "Bloquea un rango de tiempo para que no se agenden citas. "
            "Puede ser un bloque de horas en un día o un rango de días completos."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "start_date": {
                    "type": "string",
                    "description": "Fecha de inicio en formato YYYY-MM-DD.",
                },
                "end_date": {
                    "type": "string",
                    "description": "Fecha de fin en formato YYYY-MM-DD (inclusive). Si no se proporciona, es el mismo día que start_date.",
                },
                "start_time": {
                    "type": "string",
                    "description": "Hora de inicio del bloqueo en formato HH:MM. Si no se proporciona, se bloquea todo el día.",
                },
                "end_time": {
                    "type": "string",
                    "description": "Hora de fin del bloqueo en formato HH:MM. Requerido si se proporciona start_time.",
                },
                "reason": {
                    "type": "string",
                    "description": "Motivo del bloqueo (ej: 'Vacaciones', 'Junta', 'Personal').",
                },
            },
            "required": ["start_date", "reason"],
        },
    },
    {
        "name": "send_message_to_patient",
        "description": (
            "Envía un mensaje de WhatsApp a un paciente específico. "
            "El paciente se identifica por nombre."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "patient_name": {
                    "type": "string",
                    "description": "Nombre (o parte del nombre) del paciente.",
                },
                "message": {
                    "type": "string",
                    "description": "Texto del mensaje a enviar.",
                },
            },
            "required": ["patient_name", "message"],
        },
    },
    {
        "name": "mark_appointment_status",
        "description": (
            "Marca una cita como completada o no_show (el paciente no se presentó)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "appointment_id": {
                    "type": "string",
                    "description": "ID de la cita.",
                },
                "status": {
                    "type": "string",
                    "enum": ["completed", "no_show"],
                    "description": "Nuevo estado: 'completed' o 'no_show'.",
                },
            },
            "required": ["appointment_id", "status"],
        },
    },
    {
        "name": "add_appointment_note",
        "description": "Agrega o actualiza las notas de una cita.",
        "input_schema": {
            "type": "object",
            "properties": {
                "appointment_id": {
                    "type": "string",
                    "description": "ID de la cita.",
                },
                "note": {
                    "type": "string",
                    "description": "Texto de la nota.",
                },
            },
            "required": ["appointment_id", "note"],
        },
    },
]


# ---------------------------------------------------------------------------
# Doctor tool context
# ---------------------------------------------------------------------------

class DoctorToolContext:
    """Context for doctor tool handlers."""

    def __init__(
        self,
        db: AsyncSession,
        office: Office,
        redis_client: redis.Redis,
        meta_client: MetaCloudClient,
    ):
        self.db = db
        self.office = office
        self.redis_client = redis_client
        self.meta_client = meta_client


# ---------------------------------------------------------------------------
# Tool executor
# ---------------------------------------------------------------------------

_HANDLERS: dict[str, Any] = {}


def _handler(name: str):
    """Decorator to register a doctor tool handler."""
    def decorator(fn):
        _HANDLERS[name] = fn
        return fn
    return decorator


async def execute_doctor_tool(
    tool_name: str,
    arguments: dict,
    ctx: DoctorToolContext,
) -> dict:
    """Execute a doctor tool by name."""
    handler = _HANDLERS.get(tool_name)
    if not handler:
        return {"error": f"Herramienta desconocida: {tool_name}"}

    try:
        return await handler(arguments, ctx)
    except Exception as e:
        logger.error("doctor_tool_execution_error", tool=tool_name, error=str(e), exc_info=True)
        return {"error": f"Error al ejecutar {tool_name}: {str(e)}"}


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------

@_handler("get_appointments_by_date")
async def _handle_get_appointments(args: dict, ctx: DoctorToolContext) -> dict:
    date_str = args.get("date", "")
    if not date_str:
        target_date = datetime.now(tz=MX_TIMEZONE).date()
    else:
        try:
            target_date = date_cls.fromisoformat(date_str)
        except ValueError:
            return {"error": f"Fecha invalida: {date_str}. Usa formato YYYY-MM-DD."}

    time_min = datetime.combine(target_date, datetime.min.time()).replace(tzinfo=MX_TIMEZONE)
    time_max = datetime.combine(target_date, datetime.max.time()).replace(tzinfo=MX_TIMEZONE)

    stmt = (
        select(Appointment)
        .where(
            (Appointment.office_id == ctx.office.id)
            & (Appointment.start_datetime >= time_min)
            & (Appointment.start_datetime <= time_max)
            & (Appointment.status.in_(["scheduled", "confirmed"]))
        )
        .order_by(Appointment.start_datetime)
    )
    result = await ctx.db.execute(stmt)
    appointments = result.scalars().all()

    if not appointments:
        day_name = DAYS_ES[target_date.weekday()]
        return {
            "date": target_date.isoformat(),
            "day_name": day_name,
            "appointments": [],
            "message": f"No hay citas para {day_name} {target_date.strftime('%d/%m/%Y')}.",
        }

    appt_list = []
    for appt in appointments:
        dt = appt.start_datetime
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=MX_TIMEZONE)

        # Get patient name
        patient_name = "Sin nombre"
        if appt.patient_id:
            patient = await ctx.db.get(Patient, appt.patient_id)
            if patient and patient.name:
                patient_name = patient.name

        appt_list.append({
            "id": str(appt.id),
            "time": dt.strftime("%H:%M"),
            "patient_name": patient_name,
            "reason": appt.consultation_reason or "Consulta",
            "status": appt.status,
            "notes": appt.post_consultation_notes or "",
        })

    day_name = DAYS_ES[target_date.weekday()]
    return {
        "date": target_date.isoformat(),
        "day_name": day_name,
        "total": len(appt_list),
        "appointments": appt_list,
    }


@_handler("cancel_appointment")
async def _handle_cancel_appointment(args: dict, ctx: DoctorToolContext) -> dict:
    appt_id_str = args.get("appointment_id", "")
    reason = args.get("reason", "Cancelada por el doctor")

    try:
        appt_id = uuid.UUID(appt_id_str)
    except ValueError:
        return {"error": f"ID de cita invalido: {appt_id_str}"}

    appointment = await ctx.db.get(Appointment, appt_id)
    if not appointment or appointment.office_id != ctx.office.id:
        return {"error": "No se encontro la cita."}

    if appointment.status == "cancelled":
        return {"error": "La cita ya fue cancelada."}

    dt = appointment.start_datetime
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=MX_TIMEZONE)
    formatted = f"{DAYS_ES[dt.weekday()]} {dt.strftime('%d/%m/%Y')} a las {dt.strftime('%H:%M')}"

    # Google Calendar first — if it fails, don't touch the DB
    if ctx.office.google_calendar_token:
        try:
            await cancel_appointment_in_calendar(appt_id, ctx.office.id, ctx.db)
        except Exception as e:
            logger.error("doctor_cancel_gcal_failed", error=str(e))
            return {"error": "No se pudo cancelar en Google Calendar. La cita no fue modificada. Intenta de nuevo."}

    appointment.status = "cancelled"
    appointment.cancelled_by = "doctor"
    appointment.cancellation_reason = reason

    logger.info("doctor_cancelled_appointment", appointment_id=appt_id_str)

    return {
        "success": True,
        "appointment_id": appt_id_str,
        "formatted": formatted,
        "reason": reason,
    }


@_handler("pause_bot")
async def _handle_pause_bot(args: dict, ctx: DoctorToolContext) -> dict:
    minutes = args.get("minutes", 60)
    if minutes <= 0:
        minutes = 60

    success = await pause_bot(ctx.office.id, minutes, ctx.redis_client)
    if success:
        return {
            "success": True,
            "minutes": minutes,
            "message": f"Bot pausado por {minutes} minutos. Los pacientes no recibirán respuestas automáticas.",
        }
    return {"error": "No se pudo pausar el bot."}


@_handler("resume_bot")
async def _handle_resume_bot(args: dict, ctx: DoctorToolContext) -> dict:
    is_paused = await check_pause(ctx.office.id, ctx.redis_client)
    if not is_paused:
        return {"success": True, "message": "El bot ya estaba activo."}

    success = await resume_bot(ctx.office.id, ctx.redis_client)
    if success:
        return {"success": True, "message": "Bot reactivado. Los pacientes recibirán respuestas automáticas."}
    return {"error": "No se pudo reanudar el bot."}


@_handler("block_time")
async def _handle_block_time(args: dict, ctx: DoctorToolContext) -> dict:
    start_date_str = args.get("start_date", "")
    end_date_str = args.get("end_date", "") or start_date_str
    start_time_str = args.get("start_time", "")
    end_time_str = args.get("end_time", "")
    reason = args.get("reason", "Bloqueado")

    try:
        start_date = date_cls.fromisoformat(start_date_str)
        end_date = date_cls.fromisoformat(end_date_str)
    except ValueError:
        return {"error": "Fecha invalida. Usa formato YYYY-MM-DD."}

    if end_date < start_date:
        return {"error": "La fecha de fin no puede ser anterior a la de inicio."}

    # Determine time range
    if start_time_str:
        try:
            s_time = datetime.strptime(start_time_str, "%H:%M").time()
            e_time = datetime.strptime(end_time_str, "%H:%M").time() if end_time_str else time_type(23, 59)
        except ValueError:
            return {"error": "Hora invalida. Usa formato HH:MM."}
    else:
        s_time = time_type(0, 0)
        e_time = time_type(23, 59)

    start_dt = datetime.combine(start_date, s_time).replace(tzinfo=MX_TIMEZONE)
    end_dt = datetime.combine(end_date, e_time).replace(tzinfo=MX_TIMEZONE)

    is_all_day = not start_time_str
    block = TimeBlock(
        id=uuid.uuid4(),
        office_id=ctx.office.id,
        start_date=start_dt,
        end_date=end_dt,
        reason=reason,
        is_all_day=is_all_day,
        origin="manual",
    )
    ctx.db.add(block)
    await ctx.db.flush()

    # Sync to Google Calendar — if it fails, rollback the TimeBlock
    if ctx.office.google_calendar_token:
        try:
            await sync_time_block(block.id, ctx.office.id, ctx.db)
        except Exception as e:
            logger.error("doctor_block_gcal_sync_failed", error=str(e))
            await ctx.db.delete(block)
            await ctx.db.flush()
            return {"error": "No se pudo crear el bloqueo en Google Calendar. Intenta de nuevo."}

    # Format response
    if start_date == end_date and start_time_str:
        formatted = f"{DAYS_ES[start_date.weekday()]} {start_date.strftime('%d/%m/%Y')} de {start_time_str} a {end_time_str}"
    elif start_date == end_date:
        formatted = f"{DAYS_ES[start_date.weekday()]} {start_date.strftime('%d/%m/%Y')} (todo el día)"
    else:
        formatted = f"Del {start_date.strftime('%d/%m/%Y')} al {end_date.strftime('%d/%m/%Y')}"

    logger.info("doctor_blocked_time", block_id=str(block.id), reason=reason)

    return {
        "success": True,
        "block_id": str(block.id),
        "formatted": formatted,
        "reason": reason,
    }


@_handler("send_message_to_patient")
async def _handle_send_message(args: dict, ctx: DoctorToolContext) -> dict:
    patient_name = args.get("patient_name", "").strip()
    message = args.get("message", "").strip()

    if not patient_name or not message:
        return {"error": "Se requiere nombre del paciente y mensaje."}

    # Search patient by name (partial match)
    stmt = select(Patient).where(
        (Patient.office_id == ctx.office.id)
        & (Patient.name.ilike(f"%{patient_name}%"))
    )
    result = await ctx.db.execute(stmt)
    patients = result.scalars().all()

    if not patients:
        return {"error": f"No se encontró paciente con nombre '{patient_name}'."}

    if len(patients) > 1:
        names = [p.name for p in patients]
        return {
            "error": "Se encontraron múltiples pacientes. Sé más específico.",
            "matches": names,
        }

    patient = patients[0]
    if not patient.whatsapp_id:
        return {"error": f"El paciente {patient.name} no tiene WhatsApp registrado."}

    try:
        await ctx.meta_client.send_text_message(
            phone_number_id=ctx.office.whatsapp_phone_id,
            token=ctx.office.whatsapp_token,
            to=patient.whatsapp_id,
            text=message,
        )
    except Exception as e:
        return {"error": f"No se pudo enviar el mensaje: {str(e)}"}

    logger.info("doctor_sent_message", patient_id=str(patient.id), patient_name=patient.name)

    return {
        "success": True,
        "patient_name": patient.name,
        "message_sent": message,
    }


@_handler("mark_appointment_status")
async def _handle_mark_status(args: dict, ctx: DoctorToolContext) -> dict:
    appt_id_str = args.get("appointment_id", "")
    new_status = args.get("status", "")

    if new_status not in ("completed", "no_show"):
        return {"error": "Estado invalido. Usa 'completed' o 'no_show'."}

    try:
        appt_id = uuid.UUID(appt_id_str)
    except ValueError:
        return {"error": f"ID de cita invalido: {appt_id_str}"}

    appointment = await ctx.db.get(Appointment, appt_id)
    if not appointment or appointment.office_id != ctx.office.id:
        return {"error": "No se encontro la cita."}

    # Update Google Calendar first — if it fails, don't change DB
    if appointment.google_event_id and ctx.office.google_calendar_token:
        try:
            # 8 = Graphite (gray/completed), 11 = Tomato (red/no_show)
            color = "8" if new_status == "completed" else "11"
            await update_event_color(ctx.office.id, appointment.google_event_id, color, ctx.db)
        except Exception as e:
            logger.error("doctor_mark_gcal_color_failed", error=str(e))
            return {"error": "No se pudo actualizar Google Calendar. El estado no fue modificado. Intenta de nuevo."}

    appointment.status = new_status

    status_label = "completada" if new_status == "completed" else "no show"
    logger.info("doctor_marked_appointment", appointment_id=appt_id_str, status=new_status)

    return {
        "success": True,
        "appointment_id": appt_id_str,
        "status": new_status,
        "message": f"Cita marcada como {status_label}.",
    }


@_handler("add_appointment_note")
async def _handle_add_note(args: dict, ctx: DoctorToolContext) -> dict:
    appt_id_str = args.get("appointment_id", "")
    note = args.get("note", "").strip()

    if not note:
        return {"error": "La nota no puede estar vacía."}

    try:
        appt_id = uuid.UUID(appt_id_str)
    except ValueError:
        return {"error": f"ID de cita invalido: {appt_id_str}"}

    appointment = await ctx.db.get(Appointment, appt_id)
    if not appointment or appointment.office_id != ctx.office.id:
        return {"error": "No se encontro la cita."}

    # Update Google Calendar first — if it fails, don't change DB
    if appointment.google_event_id and ctx.office.google_calendar_token:
        try:
            description = f"Motivo: {appointment.consultation_reason or 'Consulta'}\nNotas: {note}"
            await update_calendar_event(
                office_id=ctx.office.id,
                google_event_id=appointment.google_event_id,
                description=description,
                db=ctx.db,
            )
        except Exception as e:
            logger.error("doctor_note_gcal_update_failed", error=str(e))
            return {"error": "No se pudo actualizar Google Calendar. La nota no fue guardada. Intenta de nuevo."}

    appointment.post_consultation_notes = note

    logger.info("doctor_added_note", appointment_id=appt_id_str)

    return {
        "success": True,
        "appointment_id": appt_id_str,
        "message": "Nota agregada correctamente.",
    }
