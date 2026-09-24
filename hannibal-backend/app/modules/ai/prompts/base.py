"""Simplified system prompt for tool-use based conversation."""

from __future__ import annotations

from typing import TYPE_CHECKING, Iterable, Optional

from app.core.catalogs import insurer_labels, intake_labels, specialty_label
from app.core.constants import ReminderType
from app.utils.dates import build_date_reference_block, now_mx, time_label
from app.utils.text import sanitize_for_prompt

if TYPE_CHECKING:
    from app.db.models import Office


# Session status set by the waiting-room check-in task; while it holds, the
# patient's reply is an answer about arriving, not about confirming.
WAITING_ARRIVAL_STATUS = "waiting_arrival_report"


def gender_line_for(assistant_gender: str | None) -> str:
    """How the assistant should refer to itself grammatically.

    Spanish forces agreement on every adjective the assistant applies to itself,
    so an office that renamed the assistant to a masculine or neutral name gets
    a model contradicting itself ("soy Diego, estoy lista") unless it is told.
    """
    if assistant_gender == "masculino":
        return (
            "- Eres un asistente masculino: concuerda en masculino cuando hables "
            'de ti ("listo", "atento")'
        )
    if assistant_gender == "neutro":
        return (
            "- Evita marcar género al hablar de ti: usa formas neutras "
            '("con gusto te ayudo", "ya quedó") en vez de "listo" o "lista"'
        )
    return (
        "- Eres una asistente femenina: concuerda en femenino cuando hables de ti "
        '("lista", "atenta")'
    )


def _build_services_section(office: Office) -> str:
    """Service catalogue with prices, when the office configured one."""
    services = office.services or []
    lines = [
        f"- {s['name']}: {s.get('price') or 'precio no especificado'}"
        for s in services
        if isinstance(s, dict) and s.get("name")
    ]
    if not lines:
        return ""
    return "\n\nSERVICIOS Y PRECIOS:\n" + "\n".join(lines)


def _build_insurance_section(office: Office) -> str:
    """What the assistant may say about insurance, from structured data."""
    accepts = office.accepts_insurance
    if not accepts:
        return ""
    if accepts == "no":
        return (
            "\n\nSEGUROS:\nEl consultorio no acepta seguros médicos; "
            "la consulta se paga directamente."
        )
    names = insurer_labels(office.insurances)
    if accepts == "algunos" and names:
        return (
            "\n\nSEGUROS:\nEl consultorio acepta estos seguros: "
            + ", ".join(names)
            + ". Si el paciente menciona uno que no está en la lista, dile que lo "
            "confirmarás con el consultorio en lugar de afirmar que no se acepta."
        )
    if accepts == "si":
        listed = f" Trabaja principalmente con: {', '.join(names)}." if names else ""
        return (
            "\n\nSEGUROS:\nEl consultorio acepta seguros médicos." + listed
        )
    return ""


def _build_symptoms_section(office: Office) -> str:
    """Alarm symptoms that must reach the doctor instead of just being booked."""
    symptoms = [s for s in (office.emergency_symptoms or []) if s]
    if not symptoms:
        return ""
    return (
        "\n\nSÍNTOMAS DE ALARMA:\nSi el paciente describe alguno de estos, no lo "
        "trates como una cita normal: usa request_urgent_appointment para avisarle "
        "al doctor.\n" + "\n".join(f"- {s}" for s in symptoms)
    )


def _build_intake_section(office: Office) -> str:
    """Extra information the office wants gathered before the visit."""
    config = office.intake_questions or {}
    labels = intake_labels(config.get("preset"))
    custom = (config.get("custom") or "").strip()
    if not labels and not custom:
        return ""
    items = [f"- {label}" for label in labels]
    if custom:
        items.append(f"- {custom}")
    return (
        "\n\nANTES DE AGENDAR:\nEl consultorio quiere saber lo siguiente de cada "
        "paciente. Pregúntalo de forma natural durante la conversación, no como "
        "un cuestionario, y pásalo en intake_notes al agendar. Si el paciente no "
        "quiere contestar algo, agenda de todos modos.\n" + "\n".join(items)
    )


# DB convention for AvailabilitySchedule.day_of_week: 0=Sunday .. 6=Saturday.
_DAY_NAMES_BY_DB_DOW = ["domingo", "lunes", "martes", "miércoles", "jueves", "viernes", "sábado"]
_DB_DOW_ORDER = [1, 2, 3, 4, 5, 6, 0]  # Monday first, as people say it


def build_schedule_section(schedules: Optional[Iterable] = None) -> str:
    """Office hours, from the same AvailabilitySchedule rows the engine uses.

    Without it the assistant had no source for "¿qué horario tienen?" and
    answered from imagination. Days with identical shifts are grouped
    ("lunes a viernes").
    """
    by_day: dict[int, list[tuple]] = {}
    for sch in schedules or []:
        if getattr(sch, "is_active", True):
            by_day.setdefault(sch.day_of_week, []).append((sch.start_time, sch.end_time))
    if not by_day:
        return ""

    def shifts_text(shifts) -> str:
        return " y ".join(
            f"{time_label(start)} a {time_label(end)}" for start, end in sorted(shifts)
        )

    groups: list[tuple[list[int], str]] = []
    for dow in _DB_DOW_ORDER:
        if dow not in by_day:
            continue
        text = shifts_text(by_day[dow])
        if groups and groups[-1][1] == text and _DB_DOW_ORDER.index(groups[-1][0][-1]) + 1 == _DB_DOW_ORDER.index(dow):
            groups[-1][0].append(dow)
        else:
            groups.append(([dow], text))

    lines = []
    for days, text in groups:
        first, last = _DAY_NAMES_BY_DB_DOW[days[0]], _DAY_NAMES_BY_DB_DOW[days[-1]]
        label = first if len(days) == 1 else (f"{first} y {last}" if len(days) == 2 else f"{first} a {last}")
        lines.append(f"- {label.capitalize()}: {text}")
    return "\n\nHORARIO DE ATENCIÓN:\n" + "\n".join(lines)


def _offset_phrase(offset_minutes: int) -> str:
    """'7 días antes', '6 horas antes', '2 horas después' for a reminder offset."""
    if offset_minutes == 0:
        return "a la hora de la cita"
    minutes = abs(offset_minutes)
    when = "antes" if offset_minutes < 0 else "después"
    if minutes % 1440 == 0:
        n, unit = minutes // 1440, "día"
    elif minutes % 60 == 0:
        n, unit = minutes // 60, "hora"
    else:
        n, unit = minutes, "minuto"
    return f"{n} {unit}{'s' if n != 1 else ''} {when}"


# What each patient-facing reminder does, in the words the assistant may use
# when it tells a patient what to expect. doctor_brief goes to the doctor and is
# not the patient's business.
_REMINDER_PURPOSE = {
    ReminderType.WEEK_BEFORE.value: "recordatorio de su cita",
    ReminderType.DAY_BEFORE.value: "recordatorio donde puede confirmar o cancelar",
    ReminderType.SIX_HOURS.value: "recordatorio de su cita",
    ReminderType.AT_TIME.value: "mensaje para saber si ya llegó",
    ReminderType.POST_APPOINTMENT.value: "mensaje de seguimiento",
}


def build_capabilities_section(reminder_rules: Optional[Iterable] = None) -> str:
    """What the system really does, generated from the office's configuration.

    The assistant promised things nobody built ("te aviso si se libera un
    espacio", "te mando recordatorio una semana antes" to an office with that
    reminder off). The fix is not a list of prohibitions — it is telling the
    model what exists, from the same rows that drive the behavior, so a promise
    can only be about something real.
    """
    reminders = []
    for rule in sorted(
        (r for r in (reminder_rules or []) if getattr(r, "enabled", False)),
        key=lambda r: r.offset_minutes,
    ):
        purpose = _REMINDER_PURPOSE.get(rule.reminder_type)
        if purpose:
            reminders.append(f"{_offset_phrase(rule.offset_minutes)}: {purpose}")

    lines = [
        "\n\nLO QUE PUEDES HACER (y lo único que puedes prometer):",
        "- Con tus herramientas: consultar horarios, agendar, reagendar y cancelar citas, "
        "confirmar asistencia y avisarle al doctor de una urgencia",
    ]
    if reminders:
        lines.append(
            "- El sistema le envía al paciente, por WhatsApp y sin que tú hagas nada: "
            + "; ".join(reminders)
        )
    else:
        lines.append("- El consultorio no tiene recordatorios automáticos activados")
    lines.append(
        "- Solo te comprometes a lo que está en esta lista o a lo que ya hiciste con una "
        "herramienta. Si el paciente pide otra cosa, dile con amabilidad que por este medio "
        "no puedes hacerlo y ofrécele lo que sí"
    )
    return "\n".join(lines)


def _build_confirmation_context(active_appointment_id: str | None) -> str:
    # Confirmation guidance only exists when the office actually sent a confirmation
    # request and a cita is awaiting confirmation. Outside that case the bot must not
    # know about "confirmar" at all, so it never offers it after just booking a cita.
    if not active_appointment_id:
        return ""
    return (
        f"\n\nCONFIRMACIÓN PENDIENTE:"
        f"\nEl paciente tiene una cita pendiente de confirmar (ID: {active_appointment_id})."
        f" Usa este ID al llamar confirm_attendance o cancel_appointment."
        f"\n- Si responde afirmativamente (\"sí\", \"confirmo\", \"ahí estaré\", etc.), usa confirm_attendance"
        f"\n- Si responde negativamente (\"no\", \"no puedo\", etc.), pregunta el motivo y usa cancel_appointment"
        f"\n- Si hace una pregunta distinta, respóndela normalmente pero recuérdale que tiene esta cita pendiente de confirmar"
    )


def _build_arrival_context(active_appointment_id: str | None) -> str:
    # Only after the check-in went out at the appointment's start time. The
    # patient is standing outside (or stuck in traffic), so the whole turn is
    # about that, not about scheduling.
    if not active_appointment_id:
        return ""
    return (
        f"\n\nLLEGADA PENDIENTE:"
        f"\nAcabas de preguntarle al paciente si ya llegó a su cita (ID: {active_appointment_id})."
        f" Usa este ID al llamar report_arrival."
        f"\n- Si dice que ya está ahí (\"ya llegué\", \"estoy afuera\", \"aquí estoy\"), usa report_arrival con status=arrived"
        f"\n- Si viene en camino (\"voy llegando\", \"en 10 minutos\", \"me atoré en el tráfico\"), usa report_arrival con status=on_the_way y eta_minutes si lo menciona"
        f"\n- Si ya no puede asistir, usa cancel_appointment con este ID"
    )


def build_system_prompt(
    office: Office,
    active_appointment_id: str | None = None,
    is_returning_patient: bool = False,
    patient_name: str | None = None,
    session_status: str | None = None,
    is_first_contact: bool = False,
    reminder_rules: Optional[Iterable] = None,
    state_block: str = "",
    schedules: Optional[Iterable] = None,
) -> tuple[str, str]:
    """
    Build the system prompt for tool-use mode as (static, dynamic) parts.

    The static part depends only on office config and patient identity, so it
    stays byte-identical across the turns of a conversation — that makes it a
    cacheable prefix (OpenAI automatic prompt caching / Anthropic
    cache_control). Everything that changes per turn (current date/time,
    pending-confirmation context) goes in the dynamic tail. The AI services
    join or block-split the parts per provider.

    This prompt does NOT include available slots or patient appointments —
    the LLM queries those via tools when needed. What the tools already
    established in earlier turns arrives as `state_block` (ConversationState),
    in the dynamic part.
    """
    tone_desc = (
        "de manera formal y profesional"
        if office.assistant_tone == "formal"
        else "de manera amigable y casual"
    )
    gender_line = gender_line_for(office.assistant_gender)

    now = now_mx()
    date_reference = build_date_reference_block(now)

    custom_section = ""
    if office.custom_prompt:
        custom_section = f"""

INSTRUCCIONES PERSONALIZADAS DEL CONSULTORIO:
{office.custom_prompt}"""

    # Decided in code, not by the model: it cannot see a conversation from last
    # week (the session expired) and used to greet known patients as new ones.
    welcome_section = ""
    if office.welcome_message and is_first_contact:
        welcome_section = f"""

MENSAJE DE BIENVENIDA:
Es el primer mensaje de este paciente al consultorio: salúdalo usando este mensaje como base (puedes adaptarlo ligeramente al contexto):
"{office.welcome_message}\""""

    pricing_parts = []
    if office.new_patient_cost:
        pricing_parts.append(f"- Costo primera consulta: {office.new_patient_cost}")
    if office.returning_patient_cost:
        pricing_parts.append(f"- Costo consulta subsecuente: {office.returning_patient_cost}")
    services_section = _build_services_section(office)

    # The catalogue's first two entries are the first/returning consultation, so
    # listing both blocks would state the same two prices twice in a row.
    pricing_section = ""
    if pricing_parts and not services_section:
        pricing_section = "\n" + "\n".join(pricing_parts)

    insurance_section = _build_insurance_section(office)
    capabilities_section = build_capabilities_section(reminder_rules)
    schedule_section = build_schedule_section(schedules)
    symptoms_section = _build_symptoms_section(office)
    intake_section = _build_intake_section(office)

    # Patient type context. The name is patient-controlled free text, so
    # sanitize it before it enters the prompt (defense against injection).
    safe_patient_name = sanitize_for_prompt(patient_name)
    if is_returning_patient:
        name_line = (
            f"- Nombre registrado: {safe_patient_name}"
            if safe_patient_name
            else "- Nombre: no registrado (pídeselo)"
        )
        patient_type_section = f"""

PACIENTE ACTUAL:
Este paciente es RECURRENTE (ya ha tenido citas previas).
{name_line}
- Duración de su cita: {office.returning_patient_duration_min} minutos
- Costo de su consulta: {office.returning_patient_cost or "No especificado"}"""
    else:
        patient_type_section = f"""

PACIENTE ACTUAL:
Este paciente es NUEVO (primera vez).
- Duración de su cita: {office.new_patient_duration_min} minutos
- Costo de su consulta: {office.new_patient_cost or "No especificado"}"""

    location_parts = []
    if office.city:
        location_parts.append(office.city)
    if office.state:
        location_parts.append(office.state)
    location_str = ", ".join(location_parts) if location_parts else "No especificada"

    static_part = f"""Eres {office.assistant_name}, asistente de citas médicas para {office.name}.

INFORMACIÓN DEL CONSULTORIO:
- Nombre: {office.name}
- Especialidad: {specialty_label(office.specialty) or "No especificada"}
- Ubicación: {location_str}
- Dirección: {office.address or "No especificada"}
- Teléfono WhatsApp: {office.whatsapp_phone or "No disponible"}{schedule_section}{pricing_section}{services_section}{insurance_section}{patient_type_section}

CÓMO COMUNICARTE:
- Comunícate {tone_desc}
{gender_line}
- Respuestas cortas y claras (ideal para WhatsApp, máximo 2-3 párrafos)
- Entiende abreviaciones y lenguaje informal (ej: "xfa", "doc", "x la tarde", "pa mañana")
- Escribe fechas y horarios con el texto que te dan las herramientas (label), tal cual — no los conviertas
- Numera las opciones para que el paciente responda fácilmente (1, 2, 3...)
- No uses emojis en tus respuestas{welcome_section}

CÓMO TRABAJAR:
- Tus herramientas son la única fuente de horarios, citas y disponibilidad: consúltalas en lugar de suponer, y no afirmes que hiciste algo que ninguna herramienta ejecutó
- Para una cita nueva necesitas saber para quién es (quien escribe u otra persona), su nombre completo, el motivo y el horario. Si es para otra persona, también su teléfono. No le pidas su teléfono a quien escribe: ya lo tenemos
- Si el paciente es recurrente, su nombre ya aparece en PACIENTE ACTUAL: salúdalo por ese nombre y no se lo vuelvas a pedir
- Si algo es ambiguo (una fecha relativa con más de una lectura, una hora que puede ser de mañana o de tarde, varias citas que coinciden), di lo que entendiste y pregunta — nunca adivines. Si el paciente aclara, toma su dato y verifícalo con las herramientas
- Si el paciente tiene varias citas y quiere cancelar o reagendar, muéstraselas y pregunta cuál
- Para cancelar, pregunta el motivo antes de ejecutar la cancelación
- Si el paciente pide hablar con el doctor o dice que se siente mal, no lo mandes a esperar: pregúntale si es una emergencia. Si lo es, usa request_urgent_appointment; si no, ofrécele agendar
- NUNCA digas "déjame revisar" o "un momento" — ya tienes las herramientas, úsalas directamente{symptoms_section}{intake_section}{capabilities_section}

MENSAJES NO-TEXTO:
- Los mensajes de voz se transcriben automáticamente: si recibes "[Mensaje de voz transcrito]: ..." trátalo como un mensaje de texto normal del paciente. La transcripción puede tener errores: si una fecha, hora o nombre suena raro, confírmalo con el paciente
- Si recibes un mensaje como "[El paciente envió un mensaje de voz]" (sin transcripción), "[El paciente envió una imagen]", etc., responde amablemente que por el momento solo puedes procesar mensajes de texto y pide al paciente que escriba su solicitud
- Si el mensaje incluye un caption/texto (ej: "[El paciente envió una imagen con el texto: ...]"), responde al texto del caption normalmente
- Si el paciente mandó varios mensajes seguidos, llegan juntos en un solo turno: respóndelos juntos

REGLAS CRÍTICAS:
1. NUNCA diagnostiques enfermedades ni des consejo médico
2. Todo horario, fecha, precio, servicio o dato de una cita que menciones debe salir de una herramienta, de la información del consultorio o del ESTADO DE LA CONVERSACIÓN. Si no lo tienes, dilo o consúltalo — nunca lo inventes
3. No compartas información médica o privada del paciente
4. Distingue una urgencia de un motivo de consulta. Una urgencia es un malestar agudo que le está pasando ahora (intenso, repentino o que empeora), aunque no coincida exacto con los síntomas de alarma: pregúntale si es una emergencia y, si lo es o tienes duda, usa request_urgent_appointment. Una molestia que quiere revisar (un dolor de hace días, un chequeo, un seguimiento) es un motivo de consulta normal: agéndala. Escalar un motivo normal deja al paciente sin cita y le manda al doctor una falsa alarma{custom_section}

Tu objetivo es facilitar el agendamiento de forma eficiente y amigable. Siempre ofrece alternativas cuando algo no está disponible."""

    # The two pending-question blocks are mutually exclusive: an appointment is
    # either awaiting confirmation or awaiting an arrival report, and shipping
    # both would have the model offering to confirm a cita already under way.
    if session_status == WAITING_ARRIVAL_STATUS:
        pending_context = _build_arrival_context(active_appointment_id)
    else:
        pending_context = _build_confirmation_context(active_appointment_id)

    dynamic_part = f"{date_reference}{state_block}{pending_context}"
    return static_part, dynamic_part
