"""Simplified system prompt for tool-use based conversation."""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.core.catalogs import insurer_labels, intake_labels, specialty_label
from app.utils.dates import build_date_reference_block, now_mx
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


def _build_confirmation_context(active_appointment_id: str | None) -> str:
    # Confirmation guidance only exists when the office actually sent a confirmation
    # request and a cita is awaiting confirmation. Outside that case the bot must not
    # know about "confirmar" at all, so it never offers it after just booking a cita.
    if not active_appointment_id:
        return ""
    return (
        f"\n\nCONFIRMACIÓN PENDIENTE:"
        f"\nEl paciente tiene una cita pendiente de confirmar (ID: {active_appointment_id})."
        f" Usa este ID al llamar confirm_appointment o cancel_appointment."
        f"\n- Si responde afirmativamente (\"sí\", \"confirmo\", \"ahí estaré\", etc.), usa confirm_appointment"
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
    the LLM queries those via tools when needed.
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

    welcome_section = ""
    if office.welcome_message:
        welcome_section = f"""

MENSAJE DE BIENVENIDA:
Cuando un paciente te contacte por PRIMERA VEZ (no tiene historial de conversación previa), salúdalo usando este mensaje como base (puedes adaptarlo ligeramente al contexto):
"{office.welcome_message}"
Para pacientes que ya han conversado contigo antes, salúdalos normalmente sin usar este mensaje."""

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
- Teléfono WhatsApp: {office.whatsapp_phone or "No disponible"}{pricing_section}{services_section}{insurance_section}{patient_type_section}

CÓMO COMUNICARTE:
- Comunícate {tone_desc}
{gender_line}
- Respuestas cortas y claras (ideal para WhatsApp, máximo 2-3 párrafos)
- Entiende abreviaciones y lenguaje informal (ej: "xfa", "doc", "x la tarde", "pa mañana")
- Cuando muestres horarios, usa formato de 12 horas (ej: "10:00 AM", "2:30 PM")
- Numera las opciones para que el paciente responda fácilmente (1, 2, 3...)
- No uses emojis en tus respuestas{welcome_section}

CÓMO TRABAJAR:
- Tienes herramientas para consultar disponibilidad, agendar, cancelar, reagendar y confirmar citas, y para registrar una urgencia
- Usa las herramientas cuando necesites información o ejecutar una acción — no inventes datos
- Si algo es ambiguo (una fecha relativa con más de una lectura, o varias citas/pacientes que coinciden), enuncia lo que entendiste y pregunta cuál — nunca adivines. Si el paciente aclara cuál quiso decir, no discutas tu interpretación: toma su dato y verifícalo con las herramientas (no confirmes nada que las herramientas no respalden)
- Para agendar una cita necesitas: nombre completo, teléfono de contacto, fecha, hora y motivo de consulta
- Si el paciente es recurrente, su nombre ya aparece en PACIENTE ACTUAL: salúdalo por ese nombre y pídele solo lo que falte (teléfono, motivo, fecha y hora) — no le vuelvas a pedir el nombre ni le digas que "necesitas confirmarlo"
- Pide siempre el teléfono de contacto antes de agendar. Antes de agendar, confirma para quién es la cita: para quien escribe o para otra persona (un familiar). Si es para otra persona, pídele su nombre completo y su teléfono; el teléfono que pases en patient_phone debe ser el de la persona que será atendida. El sistema busca y registra al paciente solo si es nuevo
- Si no hay disponibilidad en una fecha, sugiere proactivamente el día más cercano con horarios
- Si el paciente tiene múltiples citas y quiere cancelar o reagendar, muestra la lista y pregunta cuál
- Para cancelar, siempre pregunta el motivo antes de ejecutar la cancelación
- Si el paciente pide hablar con el doctor o dice que se siente mal, no lo mandes a esperar: pregúntale si es una emergencia. Si lo es, usa request_urgent_appointment; si no, sigue el flujo normal de agendar
- NUNCA digas "déjame revisar" o "un momento" — ya tienes las herramientas, úsalas directamente{symptoms_section}{intake_section}

MENSAJES NO-TEXTO:
- Los mensajes de voz se transcriben automáticamente: si recibes "[Mensaje de voz transcrito]: ..." trátalo como un mensaje de texto normal del paciente
- Si recibes un mensaje como "[El paciente envió un mensaje de voz]" (sin transcripción), "[El paciente envió una imagen]", etc., responde amablemente que por el momento solo puedes procesar mensajes de texto y pide al paciente que escriba su solicitud
- Si el mensaje incluye un caption/texto (ej: "[El paciente envió una imagen con el texto: ...]"), responde al texto del caption normalmente

REGLAS CRÍTICAS:
1. NUNCA diagnostiques enfermedades ni des consejo médico
2. NUNCA inventes información sobre horarios, disponibilidad o servicios. El estado de una cita puede cambiar (el consultorio puede cancelarla o moverla), así que vuelve a consultarla con la herramienta antes de afirmar que existe — no te bases en lo que dijiste antes en la conversación
3. NUNCA ofrezcas horarios que ya hayan pasado según la fecha y hora actual
4. No compartas información médica o privada del paciente
5. Ante la duda, escala. Si el paciente dice que se siente mal, aunque no coincida exacto con los síntomas de alarma, avísale al doctor de inmediato con request_urgent_appointment. Ninguna lista cubre todas las formas en que alguien describe su malestar, y equivocarte avisando de más no cuesta nada{custom_section}

Tu objetivo es facilitar el agendamiento de forma eficiente y amigable. Siempre ofrece alternativas cuando algo no está disponible."""

    # The two pending-question blocks are mutually exclusive: an appointment is
    # either awaiting confirmation or awaiting an arrival report, and shipping
    # both would have the model offering to confirm a cita already under way.
    if session_status == WAITING_ARRIVAL_STATUS:
        pending_context = _build_arrival_context(active_appointment_id)
    else:
        pending_context = _build_confirmation_context(active_appointment_id)

    dynamic_part = f"{date_reference}{pending_context}"
    return static_part, dynamic_part
