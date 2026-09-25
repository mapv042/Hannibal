"""Tool definitions and executor for LLM tool-use based conversation."""

from __future__ import annotations

import uuid
from datetime import datetime, time, timedelta
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import ArrivalStatus, MX_TIMEZONE
from app.db.models import Appointment, Office, Patient
from app.modules.ai.tool_helpers import (
    appointment_access_error,
    availability_for_dates,
    format_appointment_dt,
    localize_mx,
    offered_slots_from,
    parse_slot_id,
    resolve_requested_days,
    resolve_active_appointment,
    resolve_appointment_duration,
    slot_id_for,
    slots_on_day,
)
from app.modules.conversation.state import (
    BookingDraft,
    ConversationState,
    KnownAppointment,
)
from app.modules.google_calendar.service import update_event_color
from app.modules.google_calendar.sync import (
    calendar_cancellation_note,
    cancel_appointment_in_calendar,
)
from app.modules.scheduling.availability import (
    invalidate_availability_cache,
    release_slot_lock,
)
from app.modules.scheduling.booking import book_appointment
from app.modules.scheduling.reschedule_notify import (
    find_pending_doctor_cancellation,
    link_pending_doctor_cancellation,
)
from app.modules.scheduling.tasks import enqueue_abandoned_reschedule_notification
from app.modules.notifications.tasks import (
    enqueue_appointment_notification,
    enqueue_cancellation_notification,
    enqueue_reschedule_notification,
)
from app.modules.audit.tasks import enqueue_write_audit
from app.utils.dates import now_mx
from app.utils.logger import get_logger
from app.utils.text import sanitize_for_prompt
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
            "Consulta los horarios libres de uno o varios días. Cuando el paciente nombra el día "
            "con palabras, pásalas tal cual en `when` y el sistema calcula la fecha exacta; si "
            "esas palabras tienen dos lecturas, te devuelve las opciones para que le preguntes. "
            "Cada horario trae un slot_id (lo que usas para reservar) y un label (lo que le "
            "muestras al paciente, tal cual). Si ningún día consultado tiene lugar, el resultado "
            "incluye next_available con el siguiente día que sí tiene."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "when": {
                    "type": "string",
                    "description": (
                        "El día como lo dijo el paciente, con sus palabras: 'mañana', 'el "
                        "miércoles', 'el próximo martes', 'el jueves en la tarde', 'el 5', '5 "
                        "de octubre', 'la otra semana'. No lo conviertas tú a fecha."
                    ),
                },
                "dates": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Solo si ya tienes fechas exactas (de un resultado anterior o de las "
                        "opciones que eligió el paciente), o para revisar varios días ante una "
                        "pregunta abierta: YYYY-MM-DD, de 1 a 7."
                    ),
                },
                "part_of_day": {
                    "type": "string",
                    "enum": ["mañana", "tarde"],
                    "description": (
                        "Solo si el paciente pidió mañana (antes de 12:00) o tarde (desde 12:00) "
                        "y no lo dijo ya dentro de `when`."
                    ),
                },
            },
            "required": [],
        },
    },
    {
        "name": "get_patient_appointments",
        "description": (
            "Obtiene las citas próximas del paciente, incluidas las que agendó para otras "
            "personas. Úsala cuando quiera cancelar, reagendar, confirmar asistencia o "
            "preguntar por sus citas. El paciente se identifica automáticamente."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "prepare_booking",
        "description": (
            "Prepara una cita nueva o un cambio de horario y verifica en ese momento que el "
            "horario siga libre. NO agenda nada: guarda un borrador y te devuelve el resumen "
            "exacto para el paciente. La cita se agenda solo cuando el paciente acepta ese "
            "resumen y llamas confirm_booking. Si el paciente cambia algún dato, vuelve a "
            "llamarla (reemplaza el borrador). Para reagendar pasa replaces_appointment_id: se "
            "conservan el paciente y el motivo de la cita original."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "slot_id": {
                    "type": "string",
                    "description": (
                        "Horario elegido, exactamente como lo devolvió get_available_slots "
                        "(YYYY-MM-DDTHH:MM). Solo se pueden reservar horarios que ofrece el "
                        "consultorio: si el paciente pidió otra hora, la herramienta te devuelve "
                        "los horarios disponibles más cercanos de ese día."
                    ),
                },
                "for_self": {
                    "type": "boolean",
                    "description": (
                        "true si la cita es para quien escribe; false si es para otra persona "
                        "(familiar, pareja, amigo). Pregúntalo si no está claro. Al reagendar "
                        "se ignora."
                    ),
                },
                "patient_name": {
                    "type": "string",
                    "description": (
                        "Nombre completo de quien será atendido. Si la cita es para quien "
                        "escribe y su nombre ya aparece en PACIENTE ACTUAL, puedes omitirlo."
                    ),
                },
                "patient_phone": {
                    "type": "string",
                    "description": (
                        "Solo cuando for_self=false: teléfono (10 dígitos) de la persona que "
                        "será atendida, no el de quien escribe."
                    ),
                },
                "reason": {
                    "type": "string",
                    "description": "Motivo de la consulta. No hace falta al reagendar.",
                },
                "intake_notes": {
                    "type": "string",
                    "description": (
                        "Lo que el paciente respondió a las preguntas de la sección ANTES DE "
                        "AGENDAR, en una o dos líneas (ej: 'Molestia desde hace 3 días. Toma "
                        "losartán.'). El doctor lo lee antes de la consulta. Omítelo si no hay "
                        "preguntas configuradas o el paciente no quiso contestar."
                    ),
                },
                "replaces_appointment_id": {
                    "type": "string",
                    "description": (
                        "Solo para reagendar: ID de la cita que se mueve (de "
                        "get_patient_appointments o del ESTADO DE LA CONVERSACIÓN)."
                    ),
                },
                "confirm_second_same_day": {
                    "type": "boolean",
                    "description": (
                        "true SOLO cuando el paciente ya fue avisado de que tiene otra cita ese "
                        "mismo día y confirmó que aun así quiere una segunda."
                    ),
                },
            },
            "required": ["slot_id", "for_self"],
        },
    },
    {
        "name": "confirm_booking",
        "description": (
            "Agenda (o reagenda) la cita preparada con prepare_booking, exactamente como quedó "
            "en el borrador. Llámala solo cuando el paciente haya aceptado ese resumen."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "cancel_appointment",
        "description": (
            "Cancela una cita existente. El paciente debe haber identificado cuál cita "
            "cancelar y dado un motivo. Cancelar libera el horario."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "appointment_id": {
                    "type": "string",
                    "description": (
                        "ID de la cita a cancelar (de get_patient_appointments o del ESTADO DE "
                        "LA CONVERSACIÓN)."
                    ),
                },
                "reason": {
                    "type": "string",
                    "description": "Motivo de la cancelación que dio el paciente.",
                },
            },
            "required": ["appointment_id", "reason"],
        },
    },
    {
        "name": "confirm_attendance",
        "description": (
            "Registra que el paciente confirma que asistirá, en respuesta a la solicitud de "
            "confirmación o recordatorio que el consultorio le envió. Una cita recién agendada "
            "ya queda lista y no necesita este paso."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "appointment_id": {
                    "type": "string",
                    "description": "ID de la cita, tomado del bloque CONFIRMACIÓN PENDIENTE.",
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
            "urgencia; para una cita normal usa prepare_booking. Antes de llamarla pregunta el "
            "motivo de la urgencia. "
            "Este es también el único canal para llegar al doctor: si el paciente pide hablar con "
            "él o dice que se siente mal, pregúntale si es una emergencia — si lo es, úsala; si no, "
            "ofrécele agendar. No existe una forma de comunicarlo en vivo con el doctor."
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
        state: Optional[ConversationState] = None,
        turn_started_at: Optional[datetime] = None,
    ):
        self.db = db
        self.office = office
        self.patient_id = patient_id
        self.whatsapp_id = whatsapp_id
        # Optional: enables slot locking + availability-cache invalidation.
        self.redis_client = redis_client
        # The conversation's working memory (offered slots, draft, actions);
        # persisted with the session by the manager.
        self.state = state if state is not None else ConversationState()
        # A draft prepared at or after this moment was never shown to the
        # patient, so confirm_booking must not execute it (see there).
        self.turn_started_at = turn_started_at or now_mx()


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


async def _release_slot(ctx, start_dt: datetime) -> None:
    """Free the anti-collision lock on a slot the office just gave back.

    `book_appointment` holds the lock for 60s so a concurrent booker can't slip
    past the overlap check before the row is visible. When we cancel or move the
    appointment ourselves, that reasoning no longer applies and the lock is pure
    obstruction: the slot reads as free everywhere else, so the patient is
    offered it and then told "se está agendando por otra persona".
    """
    if ctx.redis_client is None:
        return
    try:
        await release_slot_lock(ctx.office.id, start_dt, ctx.redis_client)
    except Exception as e:
        logger.warning("tool_slot_lock_release_failed", error=str(e))


async def _find_same_day_appointment(
    ctx,
    patient_id: uuid.UUID,
    start_dt: datetime,
    exclude_id: Optional[uuid.UUID] = None,
) -> Optional[Appointment]:
    """An active appointment this patient already has on the same MX day, if any.

    Compared on the Mexico City calendar day rather than a UTC range, so an
    evening appointment isn't counted against the following day.
    """
    day = start_dt.astimezone(MX_TIMEZONE).date()
    day_start = datetime.combine(day, time.min, tzinfo=MX_TIMEZONE)
    day_end = datetime.combine(day, time.max, tzinfo=MX_TIMEZONE)

    conditions = (
        (Appointment.office_id == ctx.office.id)
        & (Appointment.patient_id == patient_id)
        & (Appointment.status.in_(["scheduled", "confirmed"]))
        & (Appointment.start_datetime >= day_start)
        & (Appointment.start_datetime <= day_end)
    )
    if exclude_id is not None:
        conditions = conditions & (Appointment.id != exclude_id)

    result = await ctx.db.execute(
        select(Appointment).where(conditions).order_by(Appointment.start_datetime).limit(1)
    )
    return result.scalars().first()


async def _find_patient_by_phone(ctx, phone: str) -> Optional[Patient]:
    """This office's patient registered under any form of `phone`."""
    variants = phone_match_variants(phone)
    result = await ctx.db.execute(
        select(Patient).where(
            (Patient.office_id == ctx.office.id)
            & (Patient.whatsapp_id.in_(variants) | Patient.phone.in_(variants))
        ).limit(1)
    )
    return result.scalars().first()


def _writer_contact_phone(ctx) -> str:
    """The writer's own number, normalized when possible."""
    try:
        return normalize_phone(ctx.whatsapp_id)
    except ValueError:
        return ctx.whatsapp_id


# ---------------------------------------------------------------------------
# Tool executor (dispatcher)
# ---------------------------------------------------------------------------

# Tools that change state. The conversation manager will not run the same one
# twice with the same arguments inside a single turn: the model can emit
# parallel tool calls, and two identical booking calls used to book once and
# then hit the "ya tienes una cita ese día" guard on the second — which the
# model relayed as if the patient already had the appointment. Every write here
# is also recorded in ConversationState.recent_actions by the tool loop.
MUTATING_TOOLS = frozenset({
    "confirm_booking",
    "cancel_appointment",
    "confirm_attendance",
    "report_arrival",
    "request_urgent_appointment",
})

# What a successful call of each write lets the assistant truthfully say it did.
# The reply validator (conversation/grounding.py) rejects a reply that claims an
# action no tool backs. A new write tool declares its claims here.
TOOL_CLAIMS: dict[str, frozenset[str]] = {
    # A lookup that found appointments backs stating that they exist.
    "get_patient_appointments": frozenset({"book"}),
    "confirm_booking": frozenset({"book", "reschedule"}),
    "cancel_appointment": frozenset({"cancel"}),
    "confirm_attendance": frozenset({"confirm_attendance"}),
    "report_arrival": frozenset({"notify_doctor"}),
    "request_urgent_appointment": frozenset({"notify_doctor"}),
}

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

    Each call runs inside its own SAVEPOINT. A handler that raises half-way
    through leaves nothing behind: without this, its partial writes stayed in
    the turn's transaction and were committed at the end of the turn anyway, so
    the patient was told "ocurrió un error" about an appointment that existed.
    The savepoint also keeps the session usable — a failed flush used to put it
    in pending-rollback, which made every later tool call in the same turn fail
    too ("no pude cancelar", then a retry that worked).

    Returns an error dict if the tool fails, so the LLM can communicate the
    issue to the patient naturally.
    """
    handler = _HANDLERS.get(tool_name)
    if not handler:
        return {"error": f"Herramienta desconocida: {tool_name}"}

    try:
        async with ctx.db.begin_nested():
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
    dates, part_of_day, early = resolve_requested_days(args)
    if early is not None:
        return early
    # Lay the grid out in the slot length this patient's appointment will take,
    # so we never offer a 30-minute gap and then reserve 45 on top of the next
    # appointment.
    duration_min, _ = await resolve_appointment_duration(
        ctx.db, ctx.office, ctx.patient_id
    )
    result = await availability_for_dates(
        ctx.office.id,
        dates,
        ctx.db,
        slot_minutes=duration_min,
        part_of_day=part_of_day,
    )
    if "error" not in result:
        ctx.state.remember_slots(offered_slots_from(result))
        if args.get("when"):
            # Show the model how the patient's words were read.
            result["interpreted"] = {"when": args["when"], "dates": dates, "part_of_day": part_of_day}
    return result


@_handler("get_patient_appointments")
async def _handle_get_patient_appointments(args: dict, ctx: ToolContext) -> dict:
    if not ctx.patient_id:
        ctx.state.remember_appointments([])
        return {"appointments": [], "message": "No se encontró registro del paciente."}

    now = now_mx()
    stmt = (
        select(Appointment, Patient.name)
        .join(Patient, Patient.id == Appointment.patient_id, isouter=True)
        .where(
            # Their own appointments and the ones they booked for someone else —
            # they may act on both (see appointment_access_error), so they must
            # be able to see both.
            ((Appointment.patient_id == ctx.patient_id)
             | (Appointment.booked_by_patient_id == ctx.patient_id))
            & (Appointment.office_id == ctx.office.id)
            & (Appointment.status.in_(["scheduled", "confirmed"]))
            & (Appointment.start_datetime >= now)
        )
        .order_by(Appointment.start_datetime)
    )
    rows = (await ctx.db.execute(stmt)).all()

    if not rows:
        ctx.state.remember_appointments([])
        return {"appointments": [], "message": "El paciente no tiene citas próximas."}

    appt_list = []
    known = []
    for appt, name in rows:
        label = format_appointment_dt(appt.start_datetime)
        for_other = appt.patient_id != ctx.patient_id
        entry = {
            "id": str(appt.id),
            "label": label,
            "slot_id": slot_id_for(appt.start_datetime),
            "reason": appt.consultation_reason or "Consulta",
            "status": appt.status,
        }
        if for_other:
            entry["patient_name"] = name or ""
        appt_list.append(entry)
        known.append(
            KnownAppointment(
                id=str(appt.id),
                label=label,
                status=appt.status,
                patient_name=(name or None) if for_other else None,
            )
        )

    ctx.state.remember_appointments(known)
    return {"appointments": appt_list}


@_handler("prepare_booking")
async def _handle_prepare_booking(args: dict, ctx: ToolContext) -> dict:
    """Validate a booking (or a move) now and store it as a draft.

    Nothing is written to the appointments table. The point is the order of
    events: the slot is checked *before* the patient is told "te confirmo", and
    the exact data the patient approves is what confirm_booking later writes.
    """
    start_dt = parse_slot_id(args.get("slot_id", ""))
    if isinstance(start_dt, dict):
        return start_dt
    if start_dt <= now_mx():
        return {"error": "Ese horario ya pasó. Ofrécele al paciente un horario futuro."}

    replaces_id = (args.get("replaces_appointment_id") or "").strip() or None
    confirm_second = bool(args.get("confirm_second_same_day"))
    intake_notes = (args.get("intake_notes") or "").strip() or None

    if replaces_id:
        # A move: patient, reason and duration come from the appointment itself.
        appointment, error = await _load_actionable_appointment(replaces_id, ctx)
        if error:
            return error
        if localize_mx(appointment.start_datetime) == start_dt:
            return {"error": "Ese es el mismo horario que ya tiene la cita."}
        patient = await ctx.db.get(Patient, appointment.patient_id) if appointment.patient_id else None
        patient_name = (patient.name if patient else None) or ""
        reason = appointment.consultation_reason or "Consulta"
        duration_min = appointment.duration_minutes or 30
        for_self = appointment.patient_id == ctx.patient_id
        patient_phone = None
        checked_patient_id = appointment.patient_id
        exclude_id = appointment.id
        replaces_id = str(appointment.id)  # the live one, after following any reschedule chain
        old_label = format_appointment_dt(appointment.start_datetime)
    else:
        reason = (args.get("reason") or "").strip()
        if not reason:
            return {"error": "Falta el motivo de la consulta. Pregúntaselo al paciente."}
        for_self = bool(args.get("for_self", True))
        patient_name = (args.get("patient_name") or "").strip()
        patient_phone = (args.get("patient_phone") or "").strip() or None
        exclude_id = None
        old_label = None

        if not for_self:
            if not patient_name or not patient_phone:
                return {
                    "error": (
                        "Para agendar a otra persona necesito su nombre completo y su "
                        "teléfono (10 dígitos)."
                    )
                }
            try:
                third_core = phone_core_digits(patient_phone)
            except ValueError:
                return {
                    "error": (
                        f"El teléfono '{patient_phone}' no es válido. Pídele al paciente un "
                        "número de 10 dígitos."
                    )
                }
            try:
                writer_core = phone_core_digits(ctx.whatsapp_id)
            except ValueError:
                writer_core = None
            if third_core == writer_core:
                # Same number as the writer: the system can only register one
                # patient per number, so this is booked as the writer's own.
                for_self = True
                patient_phone = None

        if for_self:
            registered = await ctx.db.get(Patient, ctx.patient_id) if ctx.patient_id else None
            patient_name = patient_name or ((registered.name or "") if registered else "")
            if not patient_name:
                return {"error": "Falta el nombre completo del paciente. Pídeselo."}
            checked_patient_id = ctx.patient_id
        else:
            existing = await _find_patient_by_phone(ctx, patient_phone)
            checked_patient_id = existing.id if existing else None

        duration_min, _ = await resolve_appointment_duration(
            ctx.db, ctx.office, checked_patient_id
        )

    # Same patient, same day: could be a second appointment they really want, or
    # the patient forgetting they already have one. Ask instead of guessing.
    if checked_patient_id is not None and not confirm_second:
        same_day = await _find_same_day_appointment(
            ctx, checked_patient_id, start_dt, exclude_id=exclude_id
        )
        if same_day is not None:
            return {
                "existing_appointment": {
                    "appointment_id": str(same_day.id),
                    "label": format_appointment_dt(same_day.start_datetime),
                    "status": same_day.status,
                },
                "next_step": (
                    "Este paciente ya tiene una cita ese mismo día. Pregúntale si quiere "
                    "mover la que ya tiene (prepare_booking con replaces_appointment_id) o si "
                    "de verdad necesita una segunda cita el mismo día — no lo asumas. Si "
                    "confirma que quiere las dos, vuelve a llamar prepare_booking con "
                    "confirm_second_same_day=true."
                ),
            }

    # Patients book only what the availability engine offers — the office's
    # grid, with its buffers — not any free minute. "Free" is not enough: a
    # 10:00 squeezed between the 9:50 and 10:40 slots kills the 9:50 and the
    # buffer, and whether that happened depended on which model was answering.
    # (The doctor, who may overbook, keeps free times in his own tools.)
    # A move keeps its own duration, but the patient was offered the grid of
    # get_available_slots (their current first-visit/follow-up length). Both
    # grids are valid here: a slot from either is free for this appointment
    # (a longer slot is free for a shorter one; a slot of its own length is
    # free by construction). Checking only one rejected the very time the
    # assistant had just offered.
    grid_lengths = {duration_min}
    if replaces_id:
        offered_length, _ = await resolve_appointment_duration(
            ctx.db, ctx.office, ctx.patient_id
        )
        if offered_length >= duration_min:
            grid_lengths.add(offered_length)
    try:
        offered = []
        for length in sorted(grid_lengths):
            offered += await slots_on_day(
                ctx.office.id, start_dt.date(), ctx.db, slot_minutes=length
            )
        offered = list({s["slot_id"]: s for s in offered}.values())
    except Exception as e:
        logger.warning("tool_prepare_booking_check_failed", error=str(e))
        return {
            "error": "No pude verificar la agenda del doctor en este momento (falla técnica).",
            "error_kind": "calendar_unavailable",
        }
    requested = slot_id_for(start_dt)
    if requested not in {s["slot_id"] for s in offered}:
        nearest = sorted(
            offered,
            key=lambda s: abs(
                (parse_slot_id(s["slot_id"]) - start_dt).total_seconds()
            ),
        )[:3]
        return {
            "error": f"El {format_appointment_dt(start_dt)} no es un horario disponible.",
            "nearest_slots": sorted(nearest, key=lambda s: s["slot_id"]),
            "next_step": (
                "Ofrécele al paciente los horarios disponibles más cercanos (nearest_slots) "
                "y usa el slot_id del que elija."
                if nearest
                else "Ese día no quedan horarios; consulta get_available_slots para ofrecerle otro día."
            ),
        }

    label = format_appointment_dt(start_dt)
    # The summary is rendered into later prompts (ESTADO DE LA CONVERSACIÓN), and
    # name and reason are the patient's free text.
    safe_name = sanitize_for_prompt(patient_name)
    if old_label:
        summary = f"Cambio de cita de {safe_name or 'el paciente'}: del {old_label} al {label}."
    else:
        summary = f"Cita para {safe_name}: {label}. Motivo: {sanitize_for_prompt(reason)}."
        if not for_self and patient_phone:
            summary += f" Teléfono de contacto: {display_or_raw(patient_phone)}."

    ctx.state.draft = BookingDraft(
        slot_id=slot_id_for(start_dt),
        label=label,
        summary=summary,
        patient_name=patient_name,
        patient_phone=patient_phone,
        for_self=for_self,
        reason=reason,
        intake_notes=intake_notes,
        replaces_appointment_id=replaces_id,
        confirm_second_same_day=confirm_second,
        created_at=now_mx().isoformat(),
    )
    logger.info(
        "tool_booking_prepared",
        office_id=str(ctx.office.id),
        slot_id=ctx.state.draft.slot_id,
        reschedule=bool(replaces_id),
    )
    return {
        "prepared": True,
        "summary": summary,
        "next_step": (
            "Muéstrale este resumen al paciente y pregúntale si lo confirma. La cita NO está "
            "agendada todavía: se agenda cuando acepte y llames confirm_booking."
        ),
    }


@_handler("confirm_booking")
async def _handle_confirm_booking(args: dict, ctx: ToolContext) -> dict:
    draft = ctx.state.draft
    if draft is None:
        return {
            "error": (
                "No hay ninguna cita preparada. Usa prepare_booking con los datos que el "
                "paciente aceptó."
            )
        }

    # The patient approves a summary they have read — which means one prepared
    # in an earlier turn. Without this, a model that wrongly announced "quedó
    # agendada" right after prepare_booking could be corrected into confirming
    # a booking the patient never saw.
    if datetime.fromisoformat(draft.created_at) >= ctx.turn_started_at:
        return {
            "error": (
                "El paciente todavía no ha visto este resumen. Muéstraselo y espera a que "
                "lo acepte antes de confirmar."
            )
        }

    start_dt = parse_slot_id(draft.slot_id)
    if isinstance(start_dt, dict) or start_dt <= now_mx():
        ctx.state.draft = None
        return {"error": "El horario preparado ya pasó. Ofrécele otro horario al paciente."}

    if draft.replaces_appointment_id:
        result = await _execute_reschedule(ctx, draft.replaces_appointment_id, start_dt)
    else:
        result = await _execute_booking(ctx, draft, start_dt)

    # A failed booking means the draft no longer matches reality (typically the
    # slot was taken in between): drop it so the model re-prepares.
    ctx.state.draft = None
    return result


async def _execute_booking(ctx: ToolContext, draft: BookingDraft, start_dt: datetime) -> dict:
    """Write a new appointment from an approved draft."""
    is_new_patient = False
    if not draft.for_self:
        # Resolve the third party by phone; register them if not found.
        patient = await _find_patient_by_phone(ctx, draft.patient_phone)
        if not patient:
            patient = Patient(
                id=uuid.uuid4(),
                office_id=ctx.office.id,
                whatsapp_id=to_whatsapp_id(draft.patient_phone),
                phone=normalize_phone(draft.patient_phone),
                name=draft.patient_name,
            )
            ctx.db.add(patient)
            await ctx.db.flush()
            is_new_patient = True
        elif not patient.name:
            patient.name = draft.patient_name
        # Do NOT touch ctx.patient_id: the session still belongs to the writer.
    else:
        # Booking for whoever is writing — use (or create) their own record.
        # whatsapp_id stays the raw Meta id (used to match incoming messages).
        patient = await ctx.db.get(Patient, ctx.patient_id) if ctx.patient_id else None
        if not patient:
            patient = Patient(
                id=uuid.uuid4(),
                office_id=ctx.office.id,
                whatsapp_id=ctx.whatsapp_id,
                phone=_writer_contact_phone(ctx),
                name=draft.patient_name,
            )
            ctx.db.add(patient)
            await ctx.db.flush()
            ctx.patient_id = patient.id
            is_new_patient = True
        else:
            if not patient.phone:
                patient.phone = _writer_contact_phone(ctx)
            if not patient.name:
                patient.name = draft.patient_name

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
        reason=draft.reason,
        appt_type=appt_type,
        gcal_title=f"Cita: {draft.patient_name}",
        gcal_description=(
            f"Motivo: {draft.reason}\n"
            f"Teléfono: {display_or_raw(patient.phone)}\n"
            f"Agendada por WhatsApp"
        ),
        redis_client=ctx.redis_client,
        booked_by_patient_id=ctx.patient_id,
        intake_notes=draft.intake_notes,
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

    label = format_appointment_dt(start_dt)
    ctx.state.known_appointments.append(
        KnownAppointment(
            id=str(appointment.id),
            label=label,
            status="scheduled",
            patient_name=None if draft.for_self else draft.patient_name,
        )
    )
    logger.info("tool_appointment_created", appointment_id=str(appointment.id), office_id=str(ctx.office.id))

    return {
        "success": True,
        "summary": f"Cita agendada: {draft.patient_name}, {label}",
        "appointment_id": str(appointment.id),
        "label": label,
        "patient_name": draft.patient_name,
        "reason": draft.reason,
        "duration_minutes": duration_min,
        "office_name": ctx.office.name,
        "office_address": ctx.office.address or "",
    }


async def _execute_reschedule(ctx: ToolContext, appointment_id: str, new_start: datetime) -> dict:
    """Move an appointment to `new_start` (book the new slot, then cancel the old)."""
    appointment, error = await _load_actionable_appointment(appointment_id, ctx)
    if error:
        return error
    appt_id = appointment.id
    appt_id_str = str(appt_id)

    old_label = format_appointment_dt(appointment.start_datetime)
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
        # Same for what the patient already told us — moving the slot is no
        # reason to make the doctor walk in without the brief.
        intake_notes=appointment.intake_notes,
        rescheduled_from=appointment.id,
    )
    if outcome.error:
        return _booking_error(outcome.error)
    new_appointment = outcome.appointment

    # Cancel old
    appointment.status = "cancelled"
    appointment.cancelled_by = "patient"
    appointment.cancellation_reason = "Reagendada por el paciente"

    try:
        await cancel_appointment_in_calendar(
            appt_id, ctx.office.id, ctx.db,
            note=calendar_cancellation_note("el paciente", moved_to=new_start),
        )
    except Exception as e:
        logger.warning("tool_reschedule_cancel_gcal_failed", error=str(e))

    await _invalidate_avail(ctx, old_date)
    await _release_slot(ctx, appointment.start_datetime)

    # The doctor hears about every move, not only the ones that answer a slot
    # they cancelled themselves — notify_reschedule reads `rescheduled_from`
    # (set above) to tell the two apart and word the message accordingly.
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

    new_label = format_appointment_dt(new_start)
    ctx.state.known_appointments = [
        a for a in ctx.state.known_appointments if a.id != appt_id_str
    ] + [
        KnownAppointment(
            id=str(new_appointment.id),
            label=new_label,
            status="scheduled",
            patient_name=patient_name if appointment.patient_id != ctx.patient_id else None,
        )
    ]
    logger.info("tool_appointment_rescheduled", old_id=appt_id_str, new_id=str(new_appointment.id))

    return {
        "success": True,
        "summary": f"Cita reagendada: del {old_label} al {new_label}",
        "old_appointment_id": appt_id_str,
        "old_label": old_label,
        "new_appointment_id": str(new_appointment.id),
        "new_label": new_label,
        "reason": reason,
        "patient_name": patient_name,
    }


async def _load_actionable_appointment(
    appt_id_str: str, ctx: ToolContext
) -> tuple[Optional[Appointment], Optional[dict]]:
    """Resolve an appointment id the patient flow is about to act on.

    Returns (appointment, None) when the caller may proceed, or (None, error)
    when it may not. Handles the three ways an id goes wrong: malformed, not
    this office's or not this patient's, and — the common one — stale because
    the appointment was rescheduled during the same conversation, in which case
    the chain is followed forward to whatever is live now.
    """
    try:
        appt_id = uuid.UUID(appt_id_str)
    except ValueError:
        return None, {"error": f"ID de cita inválido: {appt_id_str}"}

    appointment = await ctx.db.get(Appointment, appt_id)
    if not appointment or appointment.office_id != ctx.office.id:
        return None, {"error": "No se encontró la cita."}

    live = await resolve_active_appointment(ctx.db, appointment)
    if live is None:
        return None, {
            "error": "Esa cita ya fue cancelada y no hay una que la reemplace.",
            "next_step": (
                "Consulta get_patient_appointments para ver qué citas tiene "
                "realmente el paciente antes de responderle."
            ),
        }

    access_error = appointment_access_error(live, ctx)
    if access_error:
        return None, {"error": access_error}

    return live, None


@_handler("cancel_appointment")
async def _handle_cancel_appointment(args: dict, ctx: ToolContext) -> dict:
    reason = args.get("reason", "")

    appointment, error = await _load_actionable_appointment(
        args.get("appointment_id", ""), ctx
    )
    if error:
        return error
    appt_id = appointment.id
    appt_id_str = str(appt_id)

    # Format before cancelling
    dt = localize_mx(appointment.start_datetime)
    label = format_appointment_dt(appointment.start_datetime)

    # Cancel
    appointment.status = "cancelled"
    appointment.cancelled_by = "patient"
    appointment.cancellation_reason = reason

    await _invalidate_avail(ctx, dt.date())
    await _release_slot(ctx, appointment.start_datetime)

    # Notify the doctor of the patient cancellation (configurable per office).
    enqueue_cancellation_notification(appointment.id)

    # Google Calendar
    try:
        await cancel_appointment_in_calendar(
            appt_id, ctx.office.id, ctx.db,
            note=calendar_cancellation_note("el paciente", reason=reason),
        )
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

    for known in ctx.state.known_appointments:
        if known.id == appt_id_str:
            known.status = "cancelled"
    # A draft that was going to move this appointment is moot now.
    if ctx.state.draft and ctx.state.draft.replaces_appointment_id == appt_id_str:
        ctx.state.draft = None

    logger.info("tool_appointment_cancelled", appointment_id=appt_id_str)

    return {
        "success": True,
        "summary": f"Cita cancelada: {label}",
        "appointment_id": appt_id_str,
        "label": label,
        "reason": reason,
    }


@_handler("confirm_attendance")
async def _handle_confirm_attendance(args: dict, ctx: ToolContext) -> dict:
    appointment, error = await _load_actionable_appointment(
        args.get("appointment_id", ""), ctx
    )
    if error:
        return error
    appt_id_str = str(appointment.id)

    appointment.status = "confirmed"

    # Update Google Calendar color
    if appointment.google_event_id:
        try:
            await update_event_color(ctx.office.id, appointment.google_event_id, "10", ctx.db)
        except Exception as e:
            logger.warning("tool_confirm_gcal_color_failed", error=str(e))

    label = format_appointment_dt(appointment.start_datetime)
    for known in ctx.state.known_appointments:
        if known.id == appt_id_str:
            known.status = "confirmed"

    logger.info("tool_appointment_confirmed", appointment_id=appt_id_str)

    return {
        "success": True,
        "summary": f"Asistencia confirmada: {label}",
        "appointment_id": appt_id_str,
        "label": label,
        "office_name": ctx.office.name,
        "office_address": ctx.office.address or "",
    }


@_handler("report_arrival")
async def _handle_report_arrival(args: dict, ctx: ToolContext) -> dict:
    # Local import keeps Celery out of this module's import graph.
    from app.modules.notifications.tasks import enqueue_arrival_notification

    status = args.get("status", "")

    if status not in (ArrivalStatus.ARRIVED.value, ArrivalStatus.ON_THE_WAY.value):
        return {"error": f"Estado de llegada inválido: {status}"}

    appointment, error = await _load_actionable_appointment(
        args.get("appointment_id", ""), ctx
    )
    if error:
        return error
    appt_id_str = str(appointment.id)

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
    appointment.arrival_reported_at = now_mx()
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

    state_label = "ya llegó" if status == ArrivalStatus.ARRIVED.value else "viene en camino"
    return {
        "success": True,
        "summary": f"Se avisó al doctor que el paciente {state_label}",
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

    reason = (args.get("reason") or "").strip()
    if not reason:
        return {"error": "Necesito el motivo de la urgencia antes de avisar al doctor."}

    patient_name = (args.get("patient_name") or "").strip()

    # Optional preferred date+time — both required to build a concrete datetime.
    preferred_time = None
    pdate = (args.get("preferred_date") or "").strip()
    ptime = (args.get("preferred_time") or "").strip()
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
        "summary": f"Se avisó al doctor de la urgencia: {reason}",
        "next_step": (
            "Dile al paciente que estás consultando con el doctor para conseguirle un espacio "
            "urgente y que le avisarás en cuanto el doctor responda. No prometas un horario todavía. "
            "Si lo que describe puede ser grave (un síntoma de alarma, algo intenso o que empeora), "
            "dile también que no espere la respuesta: que llame al 911 o acuda a urgencias."
        ),
    }
