"""Tool definitions and handlers for doctor-facing commands."""

from __future__ import annotations

import uuid
from datetime import datetime, date as date_cls, time as time_type, timedelta
from typing import Any, Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
import redis.asyncio as redis

from app.core.constants import DAYS_ES, MX_TIMEZONE
from app.db.models import Appointment, AvailabilitySchedule, Conversation, Message, Office, Patient, TimeBlock
from app.modules.google_calendar.service import (
    create_calendar_event, get_freebusy, update_event_color, update_calendar_event,
)
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
            "Obtiene todas las citas del consultorio para una fecha o rango de fechas. "
            "Si no se especifica fecha, usa la fecha de hoy. "
            "Para consultar una semana completa, usa date como fecha de inicio y end_date como fecha de fin."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "date": {
                    "type": "string",
                    "description": "Fecha (o fecha de inicio del rango) en formato YYYY-MM-DD. Si no se proporciona, se usa hoy.",
                },
                "end_date": {
                    "type": "string",
                    "description": "Fecha de fin del rango en formato YYYY-MM-DD (inclusive). Si no se proporciona, solo se consulta la fecha de 'date'.",
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
    {
        "name": "get_available_slots",
        "description": (
            "Consulta los horarios disponibles para agendar una cita en una fecha. "
            "Usa esta herramienta para verificar disponibilidad antes de crear o reagendar citas."
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
        "name": "create_appointment",
        "description": (
            "Crea una nueva cita para un paciente. Identifica al paciente por nombre. "
            "Si el paciente no existe en el sistema, se crea automáticamente. "
            "El doctor no necesita confirmación extra — ejecuta directamente."
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
        "name": "check_message_delivery",
        "description": (
            "Verifica si un mensaje enviado a un paciente fue entregado. "
            "Usa esta herramienta cuando el doctor pregunte si un mensaje llegó."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "patient_name": {
                    "type": "string",
                    "description": "Nombre (o parte del nombre) del paciente.",
                },
            },
            "required": ["patient_name"],
        },
    },
    {
        "name": "reschedule_appointment",
        "description": (
            "Reagenda una cita existente a un nuevo horario. Cancela la cita anterior "
            "y crea una nueva atómicamente. El doctor no necesita confirmación extra."
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
    end_date_str = args.get("end_date", "")

    if not date_str:
        start_date = datetime.now(tz=MX_TIMEZONE).date()
    else:
        try:
            start_date = date_cls.fromisoformat(date_str)
        except ValueError:
            return {"error": f"Fecha invalida: {date_str}. Usa formato YYYY-MM-DD."}

    if end_date_str:
        try:
            end_date = date_cls.fromisoformat(end_date_str)
        except ValueError:
            return {"error": f"Fecha de fin invalida: {end_date_str}. Usa formato YYYY-MM-DD."}
    else:
        end_date = start_date

    time_min = datetime.combine(start_date, datetime.min.time()).replace(tzinfo=MX_TIMEZONE)
    time_max = datetime.combine(end_date, datetime.max.time()).replace(tzinfo=MX_TIMEZONE)

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

    is_range = start_date != end_date

    if not appointments:
        if is_range:
            return {
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
                "appointments": [],
                "message": f"No hay citas del {start_date.strftime('%d/%m/%Y')} al {end_date.strftime('%d/%m/%Y')}.",
            }
        day_name = DAYS_ES[start_date.weekday()]
        return {
            "date": start_date.isoformat(),
            "day_name": day_name,
            "appointments": [],
            "message": f"No hay citas para {day_name} {start_date.strftime('%d/%m/%Y')}.",
        }

    appt_list = []
    for appt in appointments:
        dt = appt.start_datetime
        dt = dt.astimezone(MX_TIMEZONE) if dt.tzinfo else dt.replace(tzinfo=MX_TIMEZONE)

        patient_name = "Sin nombre"
        if appt.patient_id:
            patient = await ctx.db.get(Patient, appt.patient_id)
            if patient and patient.name:
                patient_name = patient.name

        entry = {
            "id": str(appt.id),
            "date": dt.strftime("%Y-%m-%d"),
            "day_name": DAYS_ES[dt.weekday()],
            "time": dt.strftime("%H:%M"),
            "patient_name": patient_name,
            "reason": appt.consultation_reason or "Consulta",
            "status": appt.status,
            "notes": appt.post_consultation_notes or "",
        }
        appt_list.append(entry)

    result_dict = {"total": len(appt_list), "appointments": appt_list}
    if is_range:
        result_dict["start_date"] = start_date.isoformat()
        result_dict["end_date"] = end_date.isoformat()
    else:
        result_dict["date"] = start_date.isoformat()
        result_dict["day_name"] = DAYS_ES[start_date.weekday()]
    return result_dict


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
    dt = dt.astimezone(MX_TIMEZONE) if dt.tzinfo else dt.replace(tzinfo=MX_TIMEZONE)
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
        wa_message_id = await ctx.meta_client.send_text_message(
            phone_number_id=ctx.office.whatsapp_phone_id,
            token=ctx.office.whatsapp_token,
            to=patient.whatsapp_id,
            text=message,
        )
    except Exception as e:
        return {"error": f"No se pudo enviar el mensaje: {str(e)}"}

    # Save outgoing message with delivery tracking
    conv_stmt = select(Conversation).where(
        (Conversation.office_id == ctx.office.id)
        & (Conversation.whatsapp_id == patient.whatsapp_id)
        & (Conversation.status != "archived")
    )
    conv_result = await ctx.db.execute(conv_stmt)
    conversation = conv_result.scalar_one_or_none()
    if conversation:
        msg = Message(
            id=uuid.uuid4(),
            conversation_id=conversation.id,
            content=message,
            type="text",
            direction="outgoing",
            whatsapp_message_id=wa_message_id,
            delivery_status="sent",
        )
        ctx.db.add(msg)
        await ctx.db.flush()

    logger.info("doctor_sent_message", patient_id=str(patient.id), patient_name=patient.name, wa_message_id=wa_message_id)

    return {
        "success": True,
        "patient_name": patient.name,
        "message_sent": message,
    }


@_handler("check_message_delivery")
async def _handle_check_delivery(args: dict, ctx: DoctorToolContext) -> dict:
    patient_name = args.get("patient_name", "").strip()
    if not patient_name:
        return {"error": "Se requiere nombre del paciente."}

    # Find patient
    stmt = select(Patient).where(
        (Patient.office_id == ctx.office.id)
        & (Patient.name.ilike(f"%{patient_name}%"))
    )
    result = await ctx.db.execute(stmt)
    patients = result.scalars().all()

    if not patients:
        return {"error": f"No se encontró paciente con nombre '{patient_name}'."}
    if len(patients) > 1:
        return {"error": "Múltiples pacientes encontrados. Sé más específico.", "matches": [p.name for p in patients]}

    patient = patients[0]

    # Find conversation and last outgoing message
    conv_stmt = select(Conversation).where(
        (Conversation.office_id == ctx.office.id)
        & (Conversation.whatsapp_id == patient.whatsapp_id)
    )
    conv_result = await ctx.db.execute(conv_stmt)
    conversation = conv_result.scalar_one_or_none()
    if not conversation:
        return {"error": f"No hay conversación con {patient.name}."}

    msg_stmt = (
        select(Message)
        .where(
            (Message.conversation_id == conversation.id)
            & (Message.direction == "outgoing")
            & (Message.delivery_status.isnot(None))
        )
        .order_by(Message.created_at.desc())
        .limit(1)
    )
    msg_result = await ctx.db.execute(msg_stmt)
    last_msg = msg_result.scalar_one_or_none()

    if not last_msg:
        return {"message": f"No se encontraron mensajes enviados con tracking a {patient.name}."}

    status_labels = {
        "sent": "Enviado (sin confirmación de entrega)",
        "delivered": "Entregado al teléfono del paciente",
        "read": "Leído por el paciente",
        "failed": "Falló la entrega",
    }

    return {
        "patient_name": patient.name,
        "delivery_status": last_msg.delivery_status,
        "status_description": status_labels.get(last_msg.delivery_status, last_msg.delivery_status),
        "message_preview": last_msg.content[:100],
        "sent_at": last_msg.created_at.strftime("%Y-%m-%d %H:%M"),
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


@_handler("get_available_slots")
async def _handle_get_available_slots(args: dict, ctx: DoctorToolContext) -> dict:
    date_str = args.get("date", "")
    try:
        target_date = date_cls.fromisoformat(date_str)
    except ValueError:
        return {"error": f"Fecha invalida: {date_str}. Usa formato YYYY-MM-DD."}

    now = datetime.now(tz=MX_TIMEZONE)

    # Get schedules for the target day
    db_day = (target_date.weekday() + 1) % 7  # Python Mon=0 → DB Sun=0
    stmt = select(AvailabilitySchedule).where(
        (AvailabilitySchedule.office_id == ctx.office.id)
        & (AvailabilitySchedule.is_active == True)
        & (AvailabilitySchedule.day_of_week == db_day)
    )
    result = await ctx.db.execute(stmt)
    schedules = result.scalars().all()

    if not schedules:
        day_name = DAYS_ES[target_date.weekday()]
        return {
            "date": date_str,
            "day_name": day_name,
            "slots": [],
            "message": f"No hay horario de atencion configurado para {day_name}.",
        }

    # Google Calendar freebusy
    time_min = datetime.combine(target_date, datetime.min.time()).replace(tzinfo=MX_TIMEZONE)
    time_max = datetime.combine(target_date, datetime.max.time()).replace(tzinfo=MX_TIMEZONE)
    busy_ranges: list[tuple[datetime, datetime]] = []
    if ctx.office.google_calendar_token:
        try:
            busy_periods = await get_freebusy(ctx.office.id, time_min, time_max, ctx.db)
            for bp in busy_periods:
                start = datetime.fromisoformat(bp["start"].replace("Z", "+00:00")).astimezone(MX_TIMEZONE)
                end = datetime.fromisoformat(bp["end"].replace("Z", "+00:00")).astimezone(MX_TIMEZONE)
                busy_ranges.append((start, end))
        except Exception as e:
            logger.warning("doctor_tool_freebusy_failed", error=str(e))

    # Existing appointments for the date
    appt_stmt = select(Appointment).where(
        (Appointment.office_id == ctx.office.id)
        & (Appointment.start_datetime >= time_min)
        & (Appointment.start_datetime <= time_max)
        & (Appointment.status.in_(["scheduled", "confirmed"]))
    )
    result = await ctx.db.execute(appt_stmt)
    existing_appts = result.scalars().all()
    for appt in existing_appts:
        a_start = appt.start_datetime
        if a_start.tzinfo is None:
            a_start = a_start.replace(tzinfo=MX_TIMEZONE)
        a_end = appt.end_datetime
        if a_end and a_end.tzinfo is None:
            a_end = a_end.replace(tzinfo=MX_TIMEZONE)
        elif not a_end:
            a_end = a_start + timedelta(minutes=appt.duration_minutes or 30)
        busy_ranges.append((a_start, a_end))

    # Generate slots
    slots = []
    for sched in schedules:
        slot_duration = timedelta(minutes=sched.appointment_duration_min)
        buffer = timedelta(minutes=sched.buffer_minutes)
        slot_time = datetime.combine(target_date, sched.start_time).replace(tzinfo=MX_TIMEZONE)
        end_time = datetime.combine(target_date, sched.end_time).replace(tzinfo=MX_TIMEZONE)

        while slot_time + slot_duration <= end_time:
            slot_end = slot_time + slot_duration

            if slot_time > now:
                is_busy = any(
                    slot_time < busy_end and slot_end > busy_start
                    for busy_start, busy_end in busy_ranges
                )
                if not is_busy:
                    slots.append({
                        "time": slot_time.strftime("%H:%M"),
                        "period": "mañana" if slot_time.hour < 12 else "tarde",
                    })

            slot_time = slot_time + slot_duration + buffer

    day_name = DAYS_ES[target_date.weekday()]
    return {
        "date": date_str,
        "day_name": day_name,
        "slots": slots,
        "message": f"{'No hay' if not slots else str(len(slots))} horarios disponibles para {day_name} {target_date.strftime('%d/%m/%Y')}.",
    }


@_handler("create_appointment")
async def _handle_create_appointment(args: dict, ctx: DoctorToolContext) -> dict:
    patient_name = args.get("patient_name", "").strip()
    date_str = args.get("date", "")
    time_str = args.get("time", "")
    reason = args.get("reason", "Consulta")

    if not all([patient_name, date_str, time_str]):
        return {"error": "Faltan datos. Se requiere: nombre del paciente, fecha y hora."}

    try:
        start_dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M").replace(tzinfo=MX_TIMEZONE)
    except ValueError:
        return {"error": f"Fecha u hora invalida: {date_str} {time_str}"}

    # Find or create patient by name
    stmt = select(Patient).where(
        (Patient.office_id == ctx.office.id)
        & (Patient.name.ilike(f"%{patient_name}%"))
    )
    result = await ctx.db.execute(stmt)
    patients = result.scalars().all()

    if len(patients) > 1:
        names = [p.name for p in patients]
        return {
            "error": "Se encontraron multiples pacientes. Se mas especifico.",
            "matches": names,
        }

    if patients:
        patient = patients[0]
    else:
        patient = Patient(
            id=uuid.uuid4(),
            office_id=ctx.office.id,
            name=patient_name,
        )
        ctx.db.add(patient)
        await ctx.db.flush()

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
                title=f"Cita: {patient.name}",
                start_time=start_dt,
                end_time=end_dt,
                description=f"Motivo: {reason}\nAgendada por el doctor",
                db=ctx.db,
                color_id="9",
            )
        except Exception as e:
            logger.error("doctor_create_gcal_failed", error=str(e))

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

    day_name = DAYS_ES[start_dt.weekday()]
    logger.info("doctor_created_appointment", appointment_id=str(appointment_id))

    return {
        "success": True,
        "appointment_id": str(appointment_id),
        "patient_name": patient.name,
        "date": date_str,
        "time": time_str,
        "day_name": day_name,
        "formatted": f"{day_name} {start_dt.strftime('%d/%m/%Y')} a las {start_dt.strftime('%H:%M')}",
        "reason": reason,
        "duration_minutes": duration_min,
    }


@_handler("reschedule_appointment")
async def _handle_reschedule_appointment(args: dict, ctx: DoctorToolContext) -> dict:
    appt_id_str = args.get("appointment_id", "")
    new_date = args.get("new_date", "")
    new_time = args.get("new_time", "")

    try:
        appt_id = uuid.UUID(appt_id_str)
    except ValueError:
        return {"error": f"ID de cita invalido: {appt_id_str}"}

    appointment = await ctx.db.get(Appointment, appt_id)
    if not appointment or appointment.office_id != ctx.office.id:
        return {"error": "No se encontro la cita."}

    if appointment.status == "cancelled":
        return {"error": "La cita ya fue cancelada."}

    try:
        new_start = datetime.strptime(f"{new_date} {new_time}", "%Y-%m-%d %H:%M").replace(tzinfo=MX_TIMEZONE)
    except ValueError:
        return {"error": f"Fecha u hora invalida: {new_date} {new_time}"}

    # Format old appointment
    old_dt = appointment.start_datetime
    old_dt = old_dt.astimezone(MX_TIMEZONE) if old_dt.tzinfo else old_dt.replace(tzinfo=MX_TIMEZONE)
    old_formatted = f"{DAYS_ES[old_dt.weekday()]} {old_dt.strftime('%d/%m/%Y')} a las {old_dt.strftime('%H:%M')}"

    # Cancel old appointment in Google Calendar
    if ctx.office.google_calendar_token:
        try:
            await cancel_appointment_in_calendar(appt_id, ctx.office.id, ctx.db)
        except Exception as e:
            logger.error("doctor_reschedule_cancel_gcal_failed", error=str(e))

    appointment.status = "cancelled"
    appointment.cancelled_by = "doctor"
    appointment.cancellation_reason = "Reagendada por el doctor"

    # Get patient info
    patient_name = ""
    if appointment.patient_id:
        patient = await ctx.db.get(Patient, appointment.patient_id)
        if patient:
            patient_name = patient.name or ""

    duration = timedelta(minutes=appointment.duration_minutes or 30)
    new_end = new_start + duration
    reason = appointment.consultation_reason or "Consulta"

    # Create new Google Calendar event
    google_event_id = None
    if ctx.office.google_calendar_token:
        try:
            google_event_id = await create_calendar_event(
                office_id=ctx.office.id,
                title=f"Cita: {patient_name}",
                start_time=new_start,
                end_time=new_end,
                description=f"Motivo: {reason}\nReagendada por el doctor",
                db=ctx.db,
                color_id="9",
            )
        except Exception as e:
            logger.error("doctor_reschedule_gcal_create_failed", error=str(e))

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

    new_day_name = DAYS_ES[new_start.weekday()]
    logger.info("doctor_rescheduled_appointment", old_id=appt_id_str, new_id=str(new_appointment_id))

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
