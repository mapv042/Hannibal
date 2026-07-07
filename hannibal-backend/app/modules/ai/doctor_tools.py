"""Tool definitions and handlers for doctor-facing commands."""

from __future__ import annotations

import uuid
from datetime import datetime, date as date_cls, time as time_type, timedelta
from typing import Any
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
import redis.asyncio as redis

from app.core.constants import DAYS_ES, MX_TIMEZONE
from app.db.models import Appointment, Conversation, Message, Office, Patient, TimeBlock
from app.modules.google_calendar.service import (
    create_calendar_event, update_event_color, update_calendar_event,
)
from app.modules.reminders.scheduler import schedule_reminders_for_appointment
from app.modules.scheduling.availability import (
    check_slot_bookable,
    compute_day_availability,
    invalidate_availability_cache,
    lock_slot_temporarily,
)
from app.modules.google_calendar.sync import cancel_appointment_in_calendar, sync_time_block
from app.modules.whatsapp.coexistence import pause_bot, resume_bot, check_pause
from app.modules.whatsapp.meta_client import MetaCloudClient
from app.modules.whatsapp.window import service_window_open
from app.modules.reminders.wa_templates import (
    TEMPLATE_LANGUAGE,
    TEMPLATE_OFFICE_MESSAGE,
    build_office_message_params,
)
from app.utils.dates import relative_day_label, spanish_date_label
from app.utils.logger import get_logger
from app.utils.phone import display_or_raw, normalize_phone, to_whatsapp_id

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Tool definitions (Anthropic format — OpenAIService converts automatically)
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
            "Cancela una cita de forma definitiva: el paciente pierde su lugar. "
            "Para MOVER una cita a otro horario usa reschedule_appointment, NO cancel."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "appointment_id": {
                    "type": "string",
                    "description": "ID de la cita a cancelar (obtenido de get_appointments_by_date).",
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
            "Puede ser un bloque de horas en un día o un rango de días completos. "
            "Si ya hay citas agendadas dentro del rango, NO bloquea: devuelve la lista "
            "de citas en conflicto para que el doctor decida qué hacer."
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
                "confirm_overlap": {
                    "type": "boolean",
                    "description": "Pon true SOLO cuando el doctor ya fue avisado de que hay citas en ese horario y aun así quiere bloquearlo. Por defecto false.",
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
                    "description": (
                        "Solo el contenido central del mensaje, SIN saludo, SIN el nombre "
                        "del paciente, SIN el nombre del consultorio y SIN despedida — "
                        "el sistema agrega el saludo y el cierre automáticamente."
                    ),
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
                    "description": "ID de la cita (obtenido de get_appointments_by_date).",
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
                    "description": "ID de la cita (obtenido de get_appointments_by_date).",
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
            "Si el paciente no existe en el sistema, se crea automáticamente (en ese caso "
            "se requiere su teléfono). El doctor no necesita confirmación extra — ejecuta directamente. "
            "Valida que el horario esté libre; si está ocupado o fuera de horario devuelve el "
            "conflicto para que el doctor decida (puede sobreagendar con allow_conflict=true)."
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
                "patient_phone": {
                    "type": "string",
                    "description": (
                        "Teléfono del paciente (10 dígitos). OBLIGATORIO cuando el paciente es "
                        "nuevo (no está registrado); para un paciente ya registrado puede omitirse."
                    ),
                },
                "allow_conflict": {
                    "type": "boolean",
                    "description": (
                        "Usa true SOLO cuando el doctor ya vio el conflicto de horario y confirmó "
                        "explícitamente que quiere sobreagendar de todos modos."
                    ),
                },
                "create_new_patient": {
                    "type": "boolean",
                    "description": (
                        "Usa true SOLO cuando el doctor confirmó que es un paciente nuevo distinto "
                        "de los registrados con nombre parecido (requiere patient_phone)."
                    ),
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
            "y crea una nueva atómicamente, y le avisa al paciente automáticamente del "
            "nuevo horario por WhatsApp. El doctor no necesita confirmación extra. "
            "Valida que el nuevo horario esté libre; si está ocupado o fuera de horario "
            "devuelve el conflicto para que el doctor decida (puede sobreagendar con "
            "allow_conflict=true)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "appointment_id": {
                    "type": "string",
                    "description": "ID de la cita original a reagendar (obtenido de get_appointments_by_date).",
                },
                "new_date": {
                    "type": "string",
                    "description": "Nueva fecha en formato YYYY-MM-DD.",
                },
                "new_time": {
                    "type": "string",
                    "description": "Nueva hora en formato HH:MM (24 horas).",
                },
                "allow_conflict": {
                    "type": "boolean",
                    "description": (
                        "Usa true SOLO cuando el doctor ya vio el conflicto de horario y confirmó "
                        "explícitamente que quiere sobreagendar de todos modos."
                    ),
                },
            },
            "required": ["appointment_id", "new_date", "new_time"],
        },
    },
    {
        "name": "resolve_urgent_request",
        "description": (
            "Aprueba o rechaza una solicitud de cita URGENTE pendiente (las verás listadas en "
            "URGENCIAS PENDIENTES cuando existan). Si la apruebas, agenda la cita urgente en la "
            "fecha y hora que indique el doctor —puede sobreagendar fuera del horario normal— y le "
            "avisa al paciente automáticamente. Si la rechazas, también le avisa al paciente. "
            "El doctor no necesita confirmación extra."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "request_id": {
                    "type": "string",
                    "description": "ID de la solicitud de urgencia (de la lista URGENCIAS PENDIENTES).",
                },
                "approved": {
                    "type": "boolean",
                    "description": "true si el doctor acepta atender la urgencia, false si la rechaza.",
                },
                "date": {
                    "type": "string",
                    "description": "Fecha de la cita YYYY-MM-DD. Requerido si approved=true.",
                },
                "time": {
                    "type": "string",
                    "description": "Hora de la cita HH:MM (24 horas). Requerido si approved=true.",
                },
                "note": {
                    "type": "string",
                    "description": "Nota o motivo del doctor (opcional).",
                },
            },
            "required": ["request_id", "approved"],
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


async def _guard_slot(
    ctx: DoctorToolContext, start_dt: datetime, end_dt: datetime, allow_conflict: bool,
) -> dict | None:
    """Booking guard for doctor tools: validate the slot and take the anti-race lock.

    The doctor may deliberately overbook (allow_conflict=true, after confirming),
    which skips the availability validation but still takes the lock. The lock is
    NOT released here — its 60s TTL covers the window until the transaction
    commits, so a concurrent booker can't pass the overlap check in between.
    """
    if not allow_conflict:
        conflict = await check_slot_bookable(ctx.office.id, start_dt, end_dt, ctx.db)
        if conflict:
            return {
                "error": f"No se agendó: {conflict}",
                "next_step": (
                    "Informa el conflicto al doctor y pregúntale si quiere otro "
                    "horario (usa get_available_slots) o sobreagendar de todos "
                    "modos — si confirma sobreagendar, vuelve a llamar la "
                    "herramienta con allow_conflict=true. No lo asumas."
                ),
            }
    locked = await lock_slot_temporarily(ctx.office.id, start_dt, ctx.redis_client)
    if not locked:
        return {
            "error": (
                "Ese horario se está agendando por otra persona en este momento. "
                "Intenta de nuevo en unos segundos."
            )
        }
    return None


async def _invalidate_avail(ctx: DoctorToolContext, *dates) -> None:
    """Best-effort availability-cache invalidation for the affected dates."""
    for d in dates:
        try:
            await invalidate_availability_cache(ctx.office.id, d, ctx.redis_client)
        except Exception as e:
            logger.warning("doctor_tool_avail_cache_invalidate_failed", error=str(e))


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

    await _invalidate_avail(ctx, dt.date())

    logger.info("doctor_cancelled_appointment", appointment_id=appt_id_str)

    patient = (
        await ctx.db.get(Patient, appointment.patient_id)
        if appointment.patient_id
        else None
    )

    # The model writes and sends the patient notification itself via
    # send_message_to_patient (see the doctor prompt) — we only return the facts.
    # next_step steers the reply: it fires at reply-composition time (unlike the tool
    # description, read at selection time), so the freed-slot question reliably happens.
    return {
        "success": True,
        "appointment_id": appt_id_str,
        "formatted": formatted,
        "reason": reason,
        "patient_name": patient.name if patient else None,
        "next_step": (
            f"El horario {formatted} quedó libre y el bot podría reofrecerlo a otro "
            "paciente. Pregúntale al doctor si quiere que lo bloquees con block_time para "
            "que no se reagende, o si prefiere dejarlo abierto — no lo asumas."
        ),
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

    # Check for appointments inside the range — the doctor decides what to do with them.
    # We never block silently over existing citas.
    confirm_overlap = bool(args.get("confirm_overlap", False))
    if not confirm_overlap:
        conflicts_stmt = (
            select(Appointment)
            .where(
                (Appointment.office_id == ctx.office.id)
                & (Appointment.status.in_(["scheduled", "confirmed"]))
                & (Appointment.start_datetime < end_dt)
                & (Appointment.end_datetime > start_dt)
            )
            .order_by(Appointment.start_datetime)
        )
        conflicts = (await ctx.db.execute(conflicts_stmt)).scalars().all()

        if conflicts:
            conflict_list = []
            for appt in conflicts:
                dt = appt.start_datetime
                dt = dt.astimezone(MX_TIMEZONE) if dt.tzinfo else dt.replace(tzinfo=MX_TIMEZONE)

                patient_name = "Sin nombre"
                if appt.patient_id:
                    patient = await ctx.db.get(Patient, appt.patient_id)
                    if patient and patient.name:
                        patient_name = patient.name

                conflict_list.append({
                    "id": str(appt.id),
                    "date": dt.strftime("%Y-%m-%d"),
                    "day_name": DAYS_ES[dt.weekday()],
                    "time": dt.strftime("%H:%M"),
                    "patient_name": patient_name,
                    "reason": appt.consultation_reason or "Consulta",
                    "status": appt.status,
                })

            logger.info(
                "doctor_block_conflict",
                conflict_count=len(conflict_list),
                start=start_dt.isoformat(),
                end=end_dt.isoformat(),
            )
            return {
                "needs_confirmation": True,
                "conflicts": conflict_list,
                "next_step": (
                    "Hay citas en ese horario. Informa al doctor cuáles son y "
                    "pregúntale si quiere bloquear de todos modos (las citas se "
                    "mantienen) o cancelarlas/reagendarlas primero — no lo asumas. "
                    "Si confirma bloquear, vuelve a llamar block_time con confirm_overlap=true."
                ),
            }

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

    # Cached availability for the blocked dates is now stale (capped defensively).
    blocked_dates = [
        start_date + timedelta(days=i)
        for i in range(min((end_date - start_date).days + 1, 60))
    ]
    await _invalidate_avail(ctx, *blocked_dates)

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


async def _get_or_create_patient_conversation(
    db: AsyncSession, office_id, whatsapp_id: str
) -> Conversation:
    """Return the patient's open conversation, creating one if none exists.

    Uses limit(1) so multiple non-archived conversations never raise; the most
    recent one wins.
    """
    stmt = (
        select(Conversation)
        .where(
            (Conversation.office_id == office_id)
            & (Conversation.whatsapp_id == whatsapp_id)
            & (Conversation.status != "archived")
        )
        .order_by(Conversation.created_at.desc())
        .limit(1)
    )
    result = await db.execute(stmt)
    conversation = result.scalar_one_or_none()
    if conversation:
        return conversation

    conversation = Conversation(
        id=uuid.uuid4(),
        office_id=office_id,
        whatsapp_id=whatsapp_id,
        status="active",
    )
    db.add(conversation)
    await db.flush()
    return conversation


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
        logger.warning("doctor_send_message_no_patient", office_id=str(ctx.office.id), query=patient_name)
        return {"error": f"No se encontró paciente con nombre '{patient_name}'."}

    if len(patients) > 1:
        names = [p.name for p in patients]
        logger.warning("doctor_send_message_multiple_patients", office_id=str(ctx.office.id), query=patient_name, matches=names)
        return {
            "error": "Se encontraron múltiples pacientes. Sé más específico.",
            "matches": names,
        }

    patient = patients[0]
    if not patient.whatsapp_id:
        logger.warning("doctor_send_message_no_whatsapp", office_id=str(ctx.office.id), patient_id=str(patient.id), patient_name=patient.name)
        return {"error": f"El paciente {patient.name} no tiene WhatsApp registrado."}

    # Within the 24h window we may send the doctor's text as-is (free); outside
    # it, Meta rejects free text, so wrap it in the approved office_message
    # template (which is billed). Either way the patient gets the message.
    try:
        if await service_window_open(ctx.db, ctx.office.id, patient.whatsapp_id):
            wa_message_id = await ctx.meta_client.send_text_message(
                phone_number_id=ctx.office.whatsapp_phone_id,
                token=ctx.office.whatsapp_token,
                to=patient.whatsapp_id,
                text=message,
            )
            via = "text"
        else:
            wa_message_id = await ctx.meta_client.send_template_message(
                phone_number_id=ctx.office.whatsapp_phone_id,
                token=ctx.office.whatsapp_token,
                to=patient.whatsapp_id,
                template_name=TEMPLATE_OFFICE_MESSAGE,
                params=build_office_message_params(
                    patient_name=patient.name or "paciente",
                    location=ctx.office.name,
                    text=message,
                ),
                language_code=TEMPLATE_LANGUAGE,
            )
            via = "template"
    except Exception as e:
        logger.error(
            "doctor_send_message_send_failed",
            office_id=str(ctx.office.id),
            patient_id=str(patient.id),
            to=patient.whatsapp_id,
            error=str(e),
            exc_info=True,
        )
        return {"error": f"No se pudo enviar el mensaje: {str(e)}"}

    # Persist the outgoing message with delivery tracking
    conversation = await _get_or_create_patient_conversation(
        ctx.db, ctx.office.id, patient.whatsapp_id
    )
    msg = Message(
        id=uuid.uuid4(),
        conversation_id=conversation.id,
        content=message,
        type="text",
        direction="outgoing",
        whatsapp_message_id=wa_message_id,
        delivery_status="sent",
        extra_metadata={"via": via, "source": "doctor_send_message"},
    )
    ctx.db.add(msg)
    await ctx.db.flush()

    logger.info("doctor_sent_message", patient_id=str(patient.id), patient_name=patient.name, wa_message_id=wa_message_id)

    return {
        "success": True,
        "patient_name": patient.name,
        "message_sent": message,
        "next_step": "El mensaje fue enviado pero la entrega NO está confirmada. Usa check_message_delivery para verificar si llegó.",
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

    today = datetime.now(tz=MX_TIMEZONE).date()
    # Ground the date relative to today so the model never treats "mañana" and
    # its absolute date ("miércoles 17") as two different days.
    relative_day = relative_day_label(target_date, today)
    date_label = spanish_date_label(target_date, today)
    day_name = DAYS_ES[target_date.weekday()]

    try:
        availability = await compute_day_availability(
            ctx.office.id, target_date, ctx.db, only_future=True,
        )
    except Exception as e:
        logger.warning("doctor_tool_availability_failed", error=str(e))
        return {"error": "No se pudo consultar la disponibilidad del calendario. Intenta de nuevo en unos minutos."}

    if not availability.has_schedule:
        return {
            "date": date_str,
            "day_name": day_name,
            "relative_day": relative_day,
            "slots": [],
            "message": f"No hay horario de atencion configurado para {date_label}.",
        }

    slots = [
        {
            "time": s.start_time.strftime("%H:%M"),
            "period": "mañana" if s.start_time.hour < 12 else "tarde",
        }
        for s in availability.slots
    ]
    return {
        "date": date_str,
        "day_name": day_name,
        "relative_day": relative_day,
        "slots": slots,
        "message": f"{'No hay' if not slots else str(len(slots))} horarios disponibles para {date_label}.",
    }


@_handler("create_appointment")
async def _handle_create_appointment(args: dict, ctx: DoctorToolContext) -> dict:
    patient_name = args.get("patient_name", "").strip()
    date_str = args.get("date", "")
    time_str = args.get("time", "")
    reason = args.get("reason", "Consulta")
    patient_phone = (args.get("patient_phone") or "").strip()

    if not all([patient_name, date_str, time_str]):
        return {"error": "Faltan datos. Se requiere: nombre del paciente, fecha y hora."}

    try:
        start_dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M").replace(tzinfo=MX_TIMEZONE)
    except ValueError:
        return {"error": f"Fecha u hora invalida: {date_str} {time_str}"}

    # Find or create patient by name. create_new_patient skips the lookup when
    # the doctor confirmed it's a different, new patient with a similar name.
    create_new_patient = bool(args.get("create_new_patient", False))
    patients = []
    if not create_new_patient:
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
        registered_name = (patient.name or "").strip()
        # A single but non-exact match must be confirmed by the doctor — a
        # partial ilike can land on the wrong patient ("Ana" → "Mariana").
        if registered_name.lower() != patient_name.lower():
            return {
                "needs_confirmation": True,
                "matched_patient": registered_name,
                "next_step": (
                    f"'{patient_name}' no está registrado con ese nombre exacto; el más parecido es "
                    f"'{registered_name}'. Pregúntale al doctor si se refiere a ese paciente — no lo "
                    "asumas. Si confirma, vuelve a llamar create_appointment con el nombre exacto "
                    "registrado; si es un paciente nuevo distinto, llámala con create_new_patient=true "
                    "y su teléfono."
                ),
            }
        # Backfill the contact phone if we don't have one yet and the doctor gave it.
        if patient_phone and not patient.phone:
            try:
                patient.phone = normalize_phone(patient_phone)
            except ValueError:
                return {"error": f"El teléfono '{patient_phone}' no es válido. Usa 10 dígitos."}
    else:
        # New patient: phone is required (and fixes the NOT NULL phone/whatsapp_id columns).
        if not patient_phone:
            return {
                "error": (
                    f"'{patient_name}' es un paciente nuevo. Necesito su teléfono (10 dígitos) "
                    "para registrarlo y agendar la cita."
                )
            }
        try:
            new_phone = normalize_phone(patient_phone)
        except ValueError:
            return {"error": f"El teléfono '{patient_phone}' no es válido. Usa 10 dígitos."}
        patient = Patient(
            id=uuid.uuid4(),
            office_id=ctx.office.id,
            name=patient_name,
            phone=new_phone,
            whatsapp_id=to_whatsapp_id(patient_phone),
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

    # Validate the slot and take the anti-race lock (doctor may override
    # conflicts with allow_conflict=true after confirming).
    guard_error = await _guard_slot(
        ctx, start_dt, end_dt, bool(args.get("allow_conflict", False))
    )
    if guard_error:
        return guard_error

    # Google Calendar event
    google_event_id = None
    if ctx.office.google_calendar_token:
        try:
            google_event_id = await create_calendar_event(
                office_id=ctx.office.id,
                title=f"Cita: {patient.name}",
                start_time=start_dt,
                end_time=end_dt,
                description=(
                    f"Motivo: {reason}\n"
                    + (f"Teléfono: {display_or_raw(patient.phone)}\n" if patient.phone else "")
                    + "Agendada por el doctor"
                ),
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

    await _invalidate_avail(ctx, start_dt.date())
    await schedule_reminders_for_appointment(
        ctx.db, ctx.office.id, appointment_id, start_dt
    )

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

    # Validate the new slot and take the anti-race lock BEFORE touching the old
    # appointment, so a conflict leaves it intact. allow_conflict lets the
    # doctor overbook deliberately after confirming.
    duration = timedelta(minutes=appointment.duration_minutes or 30)
    guard_error = await _guard_slot(
        ctx, new_start, new_start + duration, bool(args.get("allow_conflict", False))
    )
    if guard_error:
        return guard_error

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
    patient_phone_display = ""
    patient_obj = (
        await ctx.db.get(Patient, appointment.patient_id)
        if appointment.patient_id
        else None
    )
    if patient_obj:
        patient_name = patient_obj.name or ""
        patient_phone_display = display_or_raw(patient_obj.phone) if patient_obj.phone else ""

    new_end = new_start + duration
    reason = appointment.consultation_reason or "Consulta"

    phone_line = f"Teléfono: {patient_phone_display}\n" if patient_phone_display else ""

    # Create new Google Calendar event
    google_event_id = None
    if ctx.office.google_calendar_token:
        try:
            google_event_id = await create_calendar_event(
                office_id=ctx.office.id,
                title=f"Cita: {patient_name}",
                start_time=new_start,
                end_time=new_end,
                description=f"Motivo: {reason}\n{phone_line}Reagendada por el doctor",
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
        type=appointment.type,
        consultation_reason=reason,
        status="scheduled",
        google_event_id=google_event_id,
    )
    ctx.db.add(new_appointment)
    await ctx.db.flush()

    await _invalidate_avail(ctx, old_dt.date(), new_start.date())
    await schedule_reminders_for_appointment(
        ctx.db, ctx.office.id, new_appointment_id, new_start
    )

    new_day_name = DAYS_ES[new_start.weekday()]
    new_formatted = f"{new_day_name} {new_start.strftime('%d/%m/%Y')} a las {new_start.strftime('%H:%M')}"
    logger.info("doctor_rescheduled_appointment", old_id=appt_id_str, new_id=str(new_appointment_id))

    # The model writes and sends the patient notification itself via
    # send_message_to_patient (see the doctor prompt) — we only return the facts.
    return {
        "success": True,
        "old_appointment_id": appt_id_str,
        "old_formatted": old_formatted,
        "new_appointment_id": str(new_appointment_id),
        "new_date": new_date,
        "new_time": new_time,
        "new_day_name": new_day_name,
        "new_formatted": new_formatted,
        "reason": reason,
        "patient_name": patient_name,
    }


@_handler("resolve_urgent_request")
async def _handle_resolve_urgent_request(args: dict, ctx: DoctorToolContext) -> dict:
    from app.modules.urgencies.service import resolve_urgency_request

    req_id_str = args.get("request_id", "")
    try:
        req_id = uuid.UUID(req_id_str)
    except ValueError:
        return {"error": f"ID de solicitud invalido: {req_id_str}"}

    approved = bool(args.get("approved", False))
    note = (args.get("note") or "").strip() or None

    start_dt = None
    if approved:
        date_str = args.get("date", "")
        time_str = args.get("time", "")
        if not (date_str and time_str):
            return {"error": "Para aprobar la urgencia necesito la fecha y la hora."}
        try:
            start_dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M").replace(tzinfo=MX_TIMEZONE)
        except ValueError:
            return {"error": f"Fecha u hora invalida: {date_str} {time_str}"}

    return await resolve_urgency_request(
        ctx.db, ctx.office, ctx.meta_client, req_id, approved, start_dt, note
    )
