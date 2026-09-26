"""Tool definitions and handlers for doctor-facing commands."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, date as date_cls, time as time_type, timedelta
from typing import Any
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
import redis.asyncio as redis

from app.core.constants import DAYS_ES, MX_TIMEZONE
from app.db.models import Appointment, Conversation, Message, Office, Patient, TimeBlock
from app.modules.google_calendar.service import (
    update_event_color, update_calendar_event,
)
from app.modules.ai.tool_helpers import (
    availability_for_dates,
    format_appointment_dt,
    localize_mx,
    offered_slots_from,
    resolve_appointment_duration,
    resolve_requested_days,
)
from app.modules.conversation.state import ConversationState
from app.modules.scheduling.availability import (
    OVERRIDABLE_CONFLICTS,
    invalidate_availability_cache,
    release_slot_lock,
)
from app.modules.scheduling.booking import book_appointment
from app.modules.audit.tasks import enqueue_write_audit
from app.modules.notifications.tasks import enqueue_reschedule_notification
from app.modules.google_calendar.sync import (
    calendar_cancellation_note,
    cancel_appointment_in_calendar,
    sync_time_block,
)
from app.modules.whatsapp.coexistence import pause_bot, resume_bot, check_pause
from app.modules.whatsapp.transport import WhatsAppClient
from app.modules.whatsapp.window import service_window_open
from app.modules.reminders.wa_templates import (
    TEMPLATE_LANGUAGE,
    TEMPLATE_OFFICE_MESSAGE,
    build_office_message_params,
)
from app.utils.dates import long_date_label, now_mx, time_label
from app.utils.logger import get_logger
from app.utils.phone import display_or_raw, normalize_phone, to_whatsapp_id, phone_match_variants

logger = get_logger(__name__)

# Pending patient-message drafts, awaiting the doctor's approval before send.
# JSON dict {patient_id: {"patient_name", "message"}} — one draft per patient.
DOCTOR_MSG_DRAFTS_KEY = "doctor_msg_drafts:{office_id}"
DOCTOR_MSG_DRAFTS_TTL = 900  # 15 minutes


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
        "description": (
            "Reanuda el bot en este momento, terminando la pausa antes de tiempo. No la uses si "
            "el doctor quiere que se reanude más tarde: la pausa termina sola al cumplirse su "
            "duración (pause_bot te dice a qué hora). Para cambiar esa hora, vuelve a llamar "
            "pause_bot con los minutos nuevos."
        ),
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
        "name": "list_time_blocks",
        "description": (
            "Lista los bloqueos de agenda vigentes del consultorio (vacaciones, juntas, "
            "días cerrados). Úsala antes de quitar un bloqueo para saber cuál es, y "
            "cuando el doctor pregunte qué tiene bloqueado."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "start_date": {
                    "type": "string",
                    "description": "Desde qué fecha listar (YYYY-MM-DD). Por defecto hoy.",
                },
                "end_date": {
                    "type": "string",
                    "description": "Hasta qué fecha listar (YYYY-MM-DD). Por defecto 90 días después.",
                },
            },
        },
    },
    {
        "name": "unblock_time",
        "description": (
            "Quita un bloqueo de agenda para que el consultorio vuelva a recibir citas "
            "en ese horario. Obtén el block_id con list_time_blocks. Solo se pueden "
            "quitar los bloqueos que puso el doctor: los que vienen de Google Calendar "
            "se quitan borrando el evento en su calendario, y los días festivos son fijos."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "block_id": {
                    "type": "string",
                    "description": "ID del bloqueo a quitar (obtenido de list_time_blocks).",
                },
            },
            "required": ["block_id"],
        },
    },
    {
        "name": "send_message_to_patient",
        "description": (
            "Guarda un BORRADOR de mensaje de WhatsApp para un paciente (identificado "
            "por nombre). NO envía nada: el doctor debe ver el texto exacto y aprobarlo, "
            "y el envío se hace con confirm_send_messages. Si el doctor pide cambios, "
            "vuelve a llamarla con el texto corregido (reemplaza el borrador anterior)."
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
        "name": "confirm_send_messages",
        "description": (
            "Envía o descarta los borradores de mensajes a pacientes pendientes. Úsala "
            "SOLO después de mostrarle al doctor el texto exacto de cada borrador: con "
            "approved=true se envían tal cual el doctor los vio (todos los pendientes); "
            "con approved=false se descartan."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "approved": {
                    "type": "boolean",
                    "description": "true si el doctor aprobó el envío; false si lo descartó.",
                },
            },
            "required": ["approved"],
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
            "Consulta los horarios disponibles en una o varias fechas (máximo 7 por llamada), "
            "cuando el doctor pregunte qué espacios tiene o te pida sugerir uno. Muestra la "
            "cuadrícula del consultorio, pero el doctor puede agendar también fuera de ella: "
            "si te da una hora exacta, no la busques aquí — create_appointment y "
            "reschedule_appointment validan esa hora y te dicen si hay conflicto. "
            "Cada horario trae un label para mostrar y un slot_id (YYYY-MM-DDTHH:MM): al crear o "
            "reagendar usa esa fecha y esa hora tal cual. Si ningún día tiene lugar, el resultado "
            "incluye next_available. Si el doctor nombra el día con palabras, pásalas en `when` "
            "y el sistema calcula la fecha."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "when": {
                    "type": "string",
                    "description": (
                        "El día como lo dijo el doctor ('mañana', 'el jueves', 'el próximo "
                        "martes', 'el 5'). No lo conviertas tú a fecha."
                    ),
                },
                "dates": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Fechas exactas YYYY-MM-DD (1 a 7), si ya las tienes.",
                },
            },
            "required": [],
        },
    },
    {
        "name": "create_appointment",
        "description": (
            "Crea una nueva cita para un paciente a la hora que diga el doctor (puede ser fuera "
            "de la cuadrícula de horarios). Identifica al paciente por nombre. "
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
                        "explícitamente que quiere sobreagendar de todos modos. Solo sirve para "
                        "encimar otra cita: un horario bloqueado o fuera del horario de atención "
                        "se rechaza igual, aunque mandes true."
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
            "y crea una nueva atómicamente. El doctor no necesita confirmación extra "
            "para reagendar; el aviso al paciente se redacta aparte con "
            "send_message_to_patient. Valida que el nuevo horario esté libre; si está "
            "ocupado o fuera de horario devuelve el conflicto para que el doctor decida "
            "(puede sobreagendar con allow_conflict=true)."
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
                        "explícitamente que quiere sobreagendar de todos modos. Solo sirve para "
                        "encimar otra cita: un horario bloqueado o fuera del horario de atención "
                        "se rechaza igual, aunque mandes true."
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
        meta_client: WhatsAppClient,
        state: ConversationState | None = None,
    ):
        self.db = db
        self.office = office
        self.redis_client = redis_client
        self.meta_client = meta_client
        # Working memory of the doctor conversation (see conversation/state.py).
        self.state = state if state is not None else ConversationState()


# ---------------------------------------------------------------------------
# Tool executor
# ---------------------------------------------------------------------------

# Tools that change state: never run twice with identical arguments in one turn
# (see BaseToolConversationManager.run_tool_loop). `confirm_send_messages` is
# deliberately here — sending the same approved drafts twice is a double message
# to the patient.
DOCTOR_MUTATING_TOOLS = frozenset({
    "cancel_appointment",
    "reschedule_appointment",
    "create_appointment",
    "block_time",
    "unblock_time",
    "mark_appointment_status",
    "add_appointment_note",
    "send_message_to_patient",
    "confirm_send_messages",
    "resolve_urgent_request",
    "pause_bot",
    "resume_bot",
})

# What a successful call of each write lets the assistant truthfully say it did
# (checked by conversation/grounding.py). A new write tool declares its claims here.
DOCTOR_TOOL_CLAIMS: dict[str, frozenset[str]] = {
    "get_appointments_by_date": frozenset({"book"}),
    "create_appointment": frozenset({"book"}),
    # A moved appointment is also "agendada" at its new time.
    "reschedule_appointment": frozenset({"reschedule", "book"}),
    "cancel_appointment": frozenset({"cancel"}),
    "confirm_send_messages": frozenset({"message_sent"}),
    # Reporting a delivery states that the message was sent.
    "check_message_delivery": frozenset({"message_sent"}),
    "resolve_urgent_request": frozenset({"book", "notify_patient"}),
}

_HANDLERS: dict[str, Any] = {}


def _handler(name: str):
    """Decorator to register a doctor tool handler."""
    def decorator(fn):
        _HANDLERS[name] = fn
        return fn
    return decorator


def _doctor_booking_error(outcome) -> dict:
    """Wrap a BookingOutcome failure for the doctor flow.

    An overlap with another appointment gets the allow_conflict escape hatch
    (the doctor may deliberately overbook after confirming). A time block or a
    slot outside working hours does not: retrying with allow_conflict=true
    fails identically, so offering it would just loop.
    """
    if outcome.conflict and outcome.conflict_kind in OVERRIDABLE_CONFLICTS:
        return {
            "error": f"No se agendó: {outcome.error}",
            "next_step": (
                "Informa el conflicto al doctor y pregúntale si quiere otro "
                "horario (usa get_available_slots) o sobreagendar de todos "
                "modos — si confirma sobreagendar, vuelve a llamar la "
                "herramienta con allow_conflict=true. No lo asumas."
            ),
        }
    if outcome.conflict:
        return {
            "error": f"No se agendó: {outcome.error}",
            "next_step": (
                "Este conflicto no se puede sobreagendar: el doctor tiene que "
                "quitar el bloqueo o ampliar su horario primero. Explícaselo y "
                "ofrécele otro horario con get_available_slots."
            ),
        }
    return {"error": outcome.error}


async def _invalidate_avail(ctx: DoctorToolContext, *dates) -> None:
    """Best-effort availability-cache invalidation for the affected dates."""
    for d in dates:
        try:
            await invalidate_availability_cache(ctx.office.id, d, ctx.redis_client)
        except Exception as e:
            logger.warning("doctor_tool_avail_cache_invalidate_failed", error=str(e))


def _format_block(block: TimeBlock) -> str:
    """Spanish description of a time block's range, as the doctor would say it."""
    start = localize_mx(block.start_date)
    end = localize_mx(block.end_date)
    if start.date() != end.date():
        return f"Del {long_date_label(start.date())} al {long_date_label(end.date())}"
    day = long_date_label(start.date())
    if block.is_all_day:
        return f"{day} (todo el día)"
    return f"{day} de {time_label(start)} a {time_label(end)}"


async def _release_slot(ctx: DoctorToolContext, start_dt: datetime) -> None:
    """Free the anti-collision lock on a slot the office just gave back.

    Mirrors app.modules.ai.tools._release_slot: the 60s lock `book_appointment`
    holds only makes sense while the appointment stands. Once we cancel or move
    it, leaving the lock means the slot reads as free everywhere but refuses to
    be booked for another minute.
    """
    try:
        await release_slot_lock(ctx.office.id, start_dt, ctx.redis_client)
    except Exception as e:
        logger.warning("doctor_tool_slot_lock_release_failed", error=str(e))


async def execute_doctor_tool(
    tool_name: str,
    arguments: dict,
    ctx: DoctorToolContext,
) -> dict:
    """Execute a doctor tool by name.

    Each call runs in its own SAVEPOINT, so a handler that raises leaves no
    half-written state behind and the session stays usable for the rest of the
    turn — see the matching note in app.modules.ai.tools.execute_tool.
    """
    handler = _HANDLERS.get(tool_name)
    if not handler:
        return {"error": f"Herramienta desconocida: {tool_name}"}

    try:
        async with ctx.db.begin_nested():
            return await handler(arguments, ctx)
    except Exception as e:
        # Log the detail; return a generic message (internal errors must not
        # leak into the doctor-facing reply the LLM composes).
        logger.error("doctor_tool_execution_error", tool=tool_name, error=str(e), exc_info=True)
        return {"error": "Ocurrió un error al ejecutar la acción. Intenta de nuevo."}


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------

@_handler("get_appointments_by_date")
async def _handle_get_appointments(args: dict, ctx: DoctorToolContext) -> dict:
    date_str = args.get("date", "")
    end_date_str = args.get("end_date", "")

    if not date_str:
        start_date = now_mx().date()
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
                "message": f"No hay citas del {long_date_label(start_date)} al {long_date_label(end_date)}.",
            }
        day_name = DAYS_ES[start_date.weekday()]
        return {
            "date": start_date.isoformat(),
            "day_name": day_name,
            "appointments": [],
            "message": f"No hay citas el {long_date_label(start_date)}.",
        }

    appt_list = []
    for appt in appointments:
        dt = localize_mx(appt.start_datetime)

        patient_name = "Sin nombre"
        if appt.patient_id:
            patient = await ctx.db.get(Patient, appt.patient_id)
            if patient and patient.name:
                patient_name = patient.name

        entry = {
            "id": str(appt.id),
            # label is what to show; slot_id carries the exact date/time for
            # reschedule_appointment (the part before T is the date).
            "label": format_appointment_dt(appt.start_datetime),
            "slot_id": dt.strftime("%Y-%m-%dT%H:%M"),
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

    dt = localize_mx(appointment.start_datetime)
    formatted = format_appointment_dt(appointment.start_datetime)

    # Google Calendar first — if it fails, don't touch the DB
    if ctx.office.google_calendar_token:
        try:
            await cancel_appointment_in_calendar(
                appt_id, ctx.office.id, ctx.db,
                note=calendar_cancellation_note("el doctor", reason=args.get("reason")),
            )
        except Exception as e:
            logger.error("doctor_cancel_gcal_failed", error=str(e))
            return {"error": "No se pudo cancelar en Google Calendar. La cita no fue modificada. Intenta de nuevo."}

    appointment.status = "cancelled"
    appointment.cancelled_by = "doctor"
    appointment.cancellation_reason = reason

    await _invalidate_avail(ctx, dt.date())
    await _release_slot(ctx, appointment.start_datetime)

    # Rule 12: confirm the slot really came free on both systems of record.
    enqueue_write_audit(appointment.id, "cancel", status="cancelled")

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
            "El paciente aún NO sabe de la cancelación: redacta su aviso con "
            "send_message_to_patient (queda como borrador para que el doctor lo apruebe). "
            f"Además, el horario {formatted} quedó libre y el bot podría reofrecerlo a otro "
            "paciente — pregúntale al doctor si quiere que lo bloquees con block_time o "
            "prefiere dejarlo abierto, no lo asumas."
        ),
    }


@_handler("pause_bot")
async def _handle_pause_bot(args: dict, ctx: DoctorToolContext) -> dict:
    minutes = args.get("minutes", 60)
    if minutes <= 0:
        minutes = 60

    success = await pause_bot(ctx.office.id, minutes, ctx.redis_client)
    if success:
        resumes_at = time_label(now_mx() + timedelta(minutes=minutes))
        return {
            "success": True,
            "minutes": minutes,
            "resumes_at": resumes_at,
            "summary": f"Bot pausado hasta las {resumes_at}",
            "message": (
                f"Bot pausado por {minutes} minutos: se reanuda solo a las {resumes_at}. "
                "Mientras tanto los pacientes no recibirán respuestas automáticas."
            ),
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

    # Blocking what is already blocked is not a new block. A repeated
    # instruction ("asegúrate de que nadie agende") used to add an identical
    # second block — and a second event in the doctor's Google Calendar.
    covering = (await ctx.db.execute(
        select(TimeBlock).where(
            (TimeBlock.office_id == ctx.office.id)
            & (TimeBlock.start_date <= start_dt)
            & (TimeBlock.end_date >= end_dt)
        ).limit(1)
    )).scalars().first()
    if covering is not None:
        label = _format_block(covering)
        return {
            "already_blocked": True,
            "block_id": str(covering.id),
            "formatted": label,
            "summary": f"Ya estaba bloqueado: {label}",
        }

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
                dt = localize_mx(appt.start_datetime)

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

    formatted = _format_block(block)

    logger.info("doctor_blocked_time", block_id=str(block.id), reason=reason)

    return {
        "success": True,
        "block_id": str(block.id),
        "formatted": formatted,
        "summary": f"Bloqueado: {formatted}",
        "reason": reason,
    }




@_handler("list_time_blocks")
async def _handle_list_time_blocks(args: dict, ctx: DoctorToolContext) -> dict:
    today = now_mx().date()
    try:
        start_date = (
            date_cls.fromisoformat(args["start_date"]) if args.get("start_date") else today
        )
        end_date = (
            date_cls.fromisoformat(args["end_date"])
            if args.get("end_date")
            else start_date + timedelta(days=90)
        )
    except ValueError:
        return {"error": "Fecha invalida. Usa formato YYYY-MM-DD."}

    range_start = datetime.combine(start_date, time_type(0, 0)).replace(tzinfo=MX_TIMEZONE)
    range_end = datetime.combine(end_date, time_type(23, 59)).replace(tzinfo=MX_TIMEZONE)

    blocks = (
        await ctx.db.execute(
            select(TimeBlock)
            .where(
                (TimeBlock.office_id == ctx.office.id)
                & (TimeBlock.start_date <= range_end)
                & (TimeBlock.end_date >= range_start)
            )
            .order_by(TimeBlock.start_date)
        )
    ).scalars().all()

    if not blocks:
        return {"blocks": [], "message": "No hay bloqueos en ese rango."}

    return {
        "blocks": [
            {
                "block_id": str(b.id),
                "formatted": _format_block(b),
                "reason": b.reason or "Sin motivo",
                "origin": b.origin,
                "removable": b.origin == "manual",
            }
            for b in blocks
        ],
    }


@_handler("unblock_time")
async def _handle_unblock_time(args: dict, ctx: DoctorToolContext) -> dict:
    try:
        block_id = uuid.UUID(args.get("block_id", ""))
    except ValueError:
        return {"error": f"ID de bloqueo invalido: {args.get('block_id', '')}"}

    block = await ctx.db.get(TimeBlock, block_id)
    if not block or block.office_id != ctx.office.id:
        return {"error": "No se encontro ese bloqueo."}

    if block.origin != "manual":
        source = (
            "Google Calendar" if block.origin == "google_calendar" else "un día festivo"
        )
        return {
            "error": f"Ese bloqueo viene de {source} y no se puede quitar desde aquí.",
            "next_step": (
                "Si viene de Google Calendar, dile al doctor que borre el evento en su "
                "calendario y el bloqueo desaparece solo."
            ),
        }

    formatted = _format_block(block)
    reason = block.reason or "Sin motivo"
    start_date = localize_mx(block.start_date).date()
    end_date = localize_mx(block.end_date).date()

    # Remove the mirrored Google Calendar event first: a block that is gone for
    # us but still on the doctor's calendar keeps the slot looking busy.
    if block.google_event_id and ctx.office.google_calendar_token:
        from app.modules.google_calendar.service import delete_calendar_event

        try:
            await delete_calendar_event(ctx.office.id, block.google_event_id, ctx.db)
        except Exception as e:
            logger.error("doctor_unblock_gcal_failed", error=str(e))
            return {
                "error": (
                    "No se pudo quitar el bloqueo en Google Calendar. "
                    "La agenda no fue modificada. Intenta de nuevo."
                )
            }

    await ctx.db.delete(block)
    await ctx.db.flush()

    unblocked_dates = [
        start_date + timedelta(days=i)
        for i in range(min((end_date - start_date).days + 1, 60))
    ]
    await _invalidate_avail(ctx, *unblocked_dates)

    logger.info("doctor_unblocked_time", block_id=str(block_id), office_id=str(ctx.office.id))

    return {
        "success": True,
        "formatted": formatted,
        "reason": reason,
        "next_step": (
            "El horario volvió a quedar disponible y el bot ya puede ofrecerlo. "
            "Confírmaselo al doctor diciéndole exactamente qué rango se liberó."
        ),
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


async def _load_message_drafts(ctx: DoctorToolContext) -> dict:
    """Load the office's pending patient-message drafts from Redis."""
    key = DOCTOR_MSG_DRAFTS_KEY.format(office_id=ctx.office.id)
    try:
        data = await ctx.redis_client.get(key)
        if data:
            return json.loads(data)
    except Exception as e:
        logger.warning("doctor_message_drafts_load_error", office_id=str(ctx.office.id), error=str(e))
    return {}


async def _save_message_drafts(ctx: DoctorToolContext, drafts: dict) -> None:
    key = DOCTOR_MSG_DRAFTS_KEY.format(office_id=ctx.office.id)
    await ctx.redis_client.setex(key, DOCTOR_MSG_DRAFTS_TTL, json.dumps(drafts))


async def _clear_message_drafts(ctx: DoctorToolContext) -> None:
    key = DOCTOR_MSG_DRAFTS_KEY.format(office_id=ctx.office.id)
    try:
        await ctx.redis_client.delete(key)
    except Exception as e:
        logger.warning("doctor_message_drafts_clear_error", office_id=str(ctx.office.id), error=str(e))


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

    # Save as a draft — nothing reaches the patient until the doctor approves
    # the exact text and the model calls confirm_send_messages. The draft is
    # what gets sent verbatim, so the preview the doctor sees is authoritative.
    drafts = await _load_message_drafts(ctx)
    drafts[str(patient.id)] = {"patient_name": patient.name, "message": message}
    await _save_message_drafts(ctx, drafts)

    logger.info(
        "doctor_message_draft_saved",
        office_id=str(ctx.office.id),
        patient_id=str(patient.id),
        pending_drafts=len(drafts),
    )

    return {
        "success": True,
        "draft_saved": True,
        "patient_name": patient.name,
        "draft_message": message,
        "next_step": (
            "El mensaje NO se ha enviado: es un borrador. Muéstrale al doctor el texto "
            "EXACTO del borrador y pregúntale si lo envía. Solo cuando lo apruebe, llama "
            "confirm_send_messages con approved=true — no lo asumas."
        ),
    }


async def _send_patient_message(ctx: DoctorToolContext, patient: Patient, message: str) -> str:
    """Send one approved message to a patient and persist it. Returns the WA message id.

    Within the 24h window we may send the text as-is (free); outside it, Meta
    rejects free text, so wrap it in the approved office_message template
    (which is billed). Either way the patient gets the message.
    """
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
    return wa_message_id


@_handler("confirm_send_messages")
async def _handle_confirm_send_messages(args: dict, ctx: DoctorToolContext) -> dict:
    approved = args.get("approved")
    if approved is None:
        return {"error": "Se requiere approved=true o approved=false."}

    drafts = await _load_message_drafts(ctx)
    if not drafts:
        return {"error": "No hay borradores pendientes. Crea uno con send_message_to_patient."}

    if not approved:
        await _clear_message_drafts(ctx)
        logger.info("doctor_message_drafts_discarded", office_id=str(ctx.office.id), count=len(drafts))
        return {
            "success": True,
            "discarded": [d["patient_name"] for d in drafts.values()],
            "next_step": "Confírmale al doctor que no se envió nada a los pacientes.",
        }

    sent_to: list[str] = []
    failed: list[str] = []
    already_sent: list[str] = []
    for patient_id_str, draft in drafts.items():
        try:
            patient = await ctx.db.get(Patient, uuid.UUID(patient_id_str))
        except ValueError:
            patient = None
        if not patient or patient.office_id != ctx.office.id or not patient.whatsapp_id:
            failed.append(draft["patient_name"])
            continue
        # The same text to the same patient twice is never what the doctor
        # means: a "sí, mándalo" repeated after the message already went out
        # used to send it again.
        sent_key = _sent_message_key(ctx.office.id, patient.id, draft["message"])
        if await ctx.redis_client.get(sent_key):
            already_sent.append(patient.name)
            continue
        try:
            await _send_patient_message(ctx, patient, draft["message"])
            await ctx.redis_client.setex(sent_key, SENT_MESSAGE_DEDUP_TTL, "1")
            sent_to.append(patient.name)
        except Exception as e:
            logger.error(
                "doctor_send_message_send_failed",
                office_id=str(ctx.office.id),
                patient_id=str(patient.id),
                to=patient.whatsapp_id,
                error=str(e),
                exc_info=True,
            )
            failed.append(patient.name)

    await _clear_message_drafts(ctx)

    if already_sent and not sent_to and not failed:
        return {
            "already_sent": already_sent,
            "next_step": (
                "Ese mismo mensaje ya se le había enviado hace poco; no se envió de nuevo. "
                "Díselo al doctor."
            ),
        }
    if not sent_to:
        return {"error": "No se pudo enviar ningún mensaje. Intenta de nuevo."}

    result = {
        "success": True,
        "sent_to": sent_to,
        "next_step": (
            "Los mensajes fueron enviados pero la entrega NO está confirmada. "
            "Usa check_message_delivery si el doctor pregunta si llegaron."
        ),
    }
    if failed:
        result["failed"] = failed
    if already_sent:
        result["already_sent"] = already_sent
    return result


# An identical message to the same patient within this window is a duplicate.
SENT_MESSAGE_DEDUP_TTL = 1800


def _sent_message_key(office_id, patient_id, message: str) -> str:
    import hashlib

    digest = hashlib.sha1(" ".join(message.lower().split()).encode()).hexdigest()[:16]
    return f"doctor_msg_sent:{office_id}:{patient_id}:{digest}"


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
    dates, part_of_day, early = resolve_requested_days(args)
    if early is not None:
        return early
    result = await availability_for_dates(
        ctx.office.id, dates, ctx.db, part_of_day=part_of_day
    )
    if "error" not in result:
        ctx.state.remember_slots(offered_slots_from(result))
    return result


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

    # The phone is the strongest identity: a patient already registered under
    # it IS this patient, whatever variant of the name the doctor typed. Looking
    # up by name alone created "Pedro Ramírez López" next to "Pedro Ramírez",
    # same phone, and booked the same person twice.
    phone_match = None
    if patient_phone:
        try:
            variants = phone_match_variants(patient_phone)
        except ValueError:
            return {"error": f"El teléfono '{patient_phone}' no es válido. Usa 10 dígitos."}
        phone_match = (await ctx.db.execute(
            select(Patient).where(
                (Patient.office_id == ctx.office.id)
                & (Patient.whatsapp_id.in_(variants) | Patient.phone.in_(variants))
            ).limit(1)
        )).scalars().first()

    # Find or create patient by name. create_new_patient skips the lookup when
    # the doctor confirmed it's a different, new patient with a similar name.
    create_new_patient = bool(args.get("create_new_patient", False))
    patients = [phone_match] if phone_match is not None else []
    if phone_match is None and not create_new_patient:
        stmt = select(Patient).where(
            (Patient.office_id == ctx.office.id)
            & (Patient.name.ilike(f"%{patient_name}%"))
        )
        result = await ctx.db.execute(stmt)
        patients = result.scalars().all()

    if len(patients) > 1:
        exact = [p for p in patients if (p.name or "").strip().lower() == patient_name.lower()]
        if len(exact) == 1:
            patients = exact
        else:
            return {
                "error": "Se encontraron varios pacientes con ese nombre. Pídele al doctor su teléfono.",
                "matches": [p.name for p in patients],
            }

    if patients:
        patient = patients[0]
        registered_name = (patient.name or "").strip()
        # A single but non-exact match must be confirmed by the doctor — a
        # partial ilike can land on the wrong patient ("Ana" → "Mariana"). A
        # phone match needs no confirmation: the number identifies them.
        if phone_match is None and registered_name.lower() != patient_name.lower():
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

    # Asking again for a cita that already exists is not a new cita. Without
    # this, a repeated instruction ("agéndalo", "sí, confírmalo") booked the
    # same patient twice at the same time.
    existing_same_slot = (await ctx.db.execute(
        select(Appointment).where(
            (Appointment.office_id == ctx.office.id)
            & (Appointment.patient_id == patient.id)
            & (Appointment.start_datetime == start_dt)
            & (Appointment.status.in_(["scheduled", "confirmed"]))
        ).limit(1)
    )).scalars().first()
    if existing_same_slot is not None:
        return {
            "already_booked": True,
            "appointment_id": str(existing_same_slot.id),
            "patient_name": patient.name,
            "label": format_appointment_dt(start_dt),
            "summary": f"{patient.name} ya estaba agendado el {format_appointment_dt(start_dt)}",
        }

    # Same definition of "first visit or follow-up" as the patient flow.
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
        gcal_title=f"Cita: {patient.name}",
        gcal_description=(
            f"Motivo: {reason}\n"
            + (f"Teléfono: {display_or_raw(patient.phone)}\n" if patient.phone else "")
            + "Agendada por el doctor"
        ),
        redis_client=ctx.redis_client,
        allow_conflict=bool(args.get("allow_conflict", False)),
    )
    if outcome.error:
        return _doctor_booking_error(outcome)
    appointment = outcome.appointment

    # Rule 12: the doctor booked this by hand — verify it reached the calendar.
    enqueue_write_audit(
        appointment.id,
        "book",
        start_datetime=start_dt,
        status="scheduled",
        patient_id=appointment.patient_id,
    )

    day_name = DAYS_ES[start_dt.weekday()]
    logger.info("doctor_created_appointment", appointment_id=str(appointment.id))

    return {
        "success": True,
        "appointment_id": str(appointment.id),
        "patient_name": patient.name,
        "date": date_str,
        "time": time_str,
        "day_name": day_name,
        "formatted": format_appointment_dt(start_dt),
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

    old_formatted = format_appointment_dt(appointment.start_datetime)
    old_date = localize_mx(appointment.start_datetime).date()
    reason = appointment.consultation_reason or "Consulta"

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
    phone_line = f"Teléfono: {patient_phone_display}\n" if patient_phone_display else ""

    # Book the new slot first — a conflict leaves the old appointment intact.
    # allow_conflict lets the doctor overbook deliberately after confirming.
    outcome = await book_appointment(
        ctx.db,
        ctx.office,
        patient_id=appointment.patient_id,
        start_dt=new_start,
        duration_min=appointment.duration_minutes or 30,
        reason=reason,
        appt_type=appointment.type,
        gcal_title=f"Cita: {patient_name}",
        gcal_description=f"Motivo: {reason}\n{phone_line}Reagendada por el doctor",
        redis_client=ctx.redis_client,
        allow_conflict=bool(args.get("allow_conflict", False)),
        booked_by_patient_id=appointment.booked_by_patient_id,
        intake_notes=appointment.intake_notes,
        rescheduled_from=appointment.id,
    )
    if outcome.error:
        return _doctor_booking_error(outcome)
    new_appointment = outcome.appointment

    # Cancel old appointment in Google Calendar
    if ctx.office.google_calendar_token:
        try:
            await cancel_appointment_in_calendar(
                appt_id, ctx.office.id, ctx.db,
                note=calendar_cancellation_note("el doctor", moved_to=new_start),
            )
        except Exception as e:
            logger.error("doctor_reschedule_cancel_gcal_failed", error=str(e))

    appointment.status = "cancelled"
    appointment.cancelled_by = "doctor"
    appointment.cancellation_reason = "Reagendada por el doctor"

    await _invalidate_avail(ctx, old_date)
    await _release_slot(ctx, appointment.start_datetime)
    enqueue_reschedule_notification(new_appointment.id)

    # Rule 12: verify both halves landed — new slot present, old slot released.
    enqueue_write_audit(
        new_appointment.id,
        "reschedule",
        start_datetime=new_start,
        status="scheduled",
        patient_id=new_appointment.patient_id,
    )
    enqueue_write_audit(appointment.id, "cancel", status="cancelled")

    new_day_name = DAYS_ES[new_start.weekday()]
    new_formatted = format_appointment_dt(new_start)
    logger.info("doctor_rescheduled_appointment", old_id=appt_id_str, new_id=str(new_appointment.id))

    # The model writes the patient notification itself via
    # send_message_to_patient (draft + doctor approval) — we return the facts.
    return {
        "success": True,
        "old_appointment_id": appt_id_str,
        "old_formatted": old_formatted,
        "new_appointment_id": str(new_appointment.id),
        "new_date": new_date,
        "new_time": new_time,
        "new_day_name": new_day_name,
        "new_formatted": new_formatted,
        "reason": reason,
        "patient_name": patient_name,
        "next_step": (
            "El paciente aún NO sabe del cambio. Redacta su aviso con "
            "send_message_to_patient (queda como borrador) y, cuando termines todos "
            "los cambios que pidió el doctor, respóndele con el resumen de citas "
            "movidas y el texto de los borradores para que apruebe el envío."
        ),
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
