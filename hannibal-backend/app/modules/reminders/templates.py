"""Reminder message templates in Spanish."""

from __future__ import annotations

from typing import Optional


def reminder_morning(appointment_data: dict, tone: str = "formal") -> str:
    """Generate morning-of-appointment reminder (sent at 8 AM)."""
    patient_name = appointment_data.get("patient_name", "estimado cliente")
    time = appointment_data.get("time", "la hora programada")
    office_name = appointment_data.get("office_name", "nuestro consultorio")
    assistant_name = appointment_data.get("assistant_name", "Asistente")

    if tone == "informal":
        return (
            f"¡Buenos días, {patient_name}! ☀️\n\n"
            f"Te recordamos que hoy tienes cita a las {time} en {office_name}.\n\n"
            f"Si necesitas cancelar o tienes dudas, avísanos. ¡Te esperamos!\n\n"
            f"— {assistant_name}"
        )
    else:
        return (
            f"Buenos días, {patient_name}.\n\n"
            f"Le recordamos que el día de hoy tiene cita a las {time} en {office_name}.\n\n"
            f"Si necesita cancelar o tiene alguna pregunta, no dude en contactarnos.\n\n"
            f"Atentamente,\n{assistant_name}"
        )


def reminder_4h(appointment_data: dict, tone: str = "formal") -> str:
    """Generate 4-hour-before reminder."""
    patient_name = appointment_data.get("patient_name", "estimado cliente")
    time = appointment_data.get("time", "la hora programada")
    office_name = appointment_data.get("office_name", "nuestro consultorio")
    assistant_name = appointment_data.get("assistant_name", "Asistente")

    if tone == "informal":
        return (
            f"¡Hola {patient_name}! 🗓️\n\n"
            f"Tu cita es en 4 horas, a las {time} en {office_name}.\n\n"
            f"Si no puedes asistir, avísanos para liberar el horario.\n\n"
            f"— {assistant_name}"
        )
    else:
        return (
            f"Estimado(a) {patient_name},\n\n"
            f"Le recordamos que su cita es en 4 horas, a las {time} en {office_name}.\n\n"
            f"Si no puede asistir, le pedimos nos avise para liberar el horario.\n\n"
            f"Atentamente,\n{assistant_name}"
        )


def reminder_1h(appointment_data: dict, tone: str = "formal") -> str:
    """Generate 1-hour-before reminder."""
    patient_name = appointment_data.get("patient_name", "estimado cliente")
    time = appointment_data.get("time", "la hora programada")
    office_name = appointment_data.get("office_name", "nuestro consultorio")
    assistant_name = appointment_data.get("assistant_name", "Asistente")

    if tone == "informal":
        return (
            f"¡{patient_name}! ⏰\n\n"
            f"Tu cita es en 1 hora, a las {time} en {office_name}.\n\n"
            f"¿Vas en camino? Si no puedes venir, avísanos.\n\n"
            f"— {assistant_name}"
        )
    else:
        return (
            f"Estimado(a) {patient_name},\n\n"
            f"Su cita es en 1 hora, a las {time} en {office_name}.\n\n"
            f"Si no puede asistir, comuníquelo a la brevedad.\n\n"
            f"Atentamente,\n{assistant_name}"
        )


def reminder_15m(appointment_data: dict, tone: str = "formal") -> str:
    """Generate 15-minute-before reminder."""
    patient_name = appointment_data.get("patient_name", "estimado cliente")
    time = appointment_data.get("time", "la hora programada")
    office_name = appointment_data.get("office_name", "nuestro consultorio")
    assistant_name = appointment_data.get("assistant_name", "Asistente")

    if tone == "informal":
        return (
            f"¡{patient_name}! 🏃\n\n"
            f"Tu cita es en 15 minutos, a las {time} en {office_name}.\n\n"
            f"¡Te esperamos!\n\n"
            f"— {assistant_name}"
        )
    else:
        return (
            f"Estimado(a) {patient_name},\n\n"
            f"Su cita es en 15 minutos, a las {time} en {office_name}.\n\n"
            f"Le esperamos.\n\n"
            f"Atentamente,\n{assistant_name}"
        )


def confirmation_request(appointment_data: dict, tone: str = "formal") -> str:
    """
    Generate day-before confirmation request message.

    Sent at 8 AM the day before the appointment asking the patient
    to confirm or cancel their attendance.

    Args:
        appointment_data: Appointment data (patient_name, date, time, office_name, assistant_name)
        tone: Message tone (formal|informal)

    Returns:
        Formatted confirmation request message
    """
    patient_name = appointment_data.get("patient_name", "estimado cliente")
    time = appointment_data.get("time", "la hora programada")
    date = appointment_data.get("date", "mañana")
    office_name = appointment_data.get("office_name", "nuestro consultorio")
    assistant_name = appointment_data.get("assistant_name", "Asistente")

    if tone == "informal":
        return (
            f"¡Hola {patient_name}! 📋\n\n"
            f"Te escribo para confirmar tu cita de mañana {date} a las {time} en {office_name}.\n\n"
            f"Por favor responde:\n"
            f"  *Sí* para confirmar tu asistencia\n"
            f"  *No* si necesitas cancelar\n\n"
            f"— {assistant_name}"
        )
    else:  # formal
        return (
            f"Estimado(a) {patient_name},\n\n"
            f"Le contactamos para confirmar su cita programada para mañana {date} a las {time} "
            f"en {office_name}.\n\n"
            f"Por favor responda:\n"
            f"  *Sí* para confirmar su asistencia\n"
            f"  *No* si necesita cancelar\n\n"
            f"Atentamente,\n{assistant_name}"
        )


def post_appointment_followup(
    appointment_data: dict, instructions: Optional[str] = None, tone: str = "formal"
) -> str:
    """
    Generate post-appointment follow-up message.

    Args:
        appointment_data: Appointment data
        instructions: Medical instructions provided
        tone: Message tone (formal|informal)

    Returns:
        Formatted follow-up message
    """
    patient_name = appointment_data.get("patient_name", "estimado cliente")
    professional_name = appointment_data.get("professional_name", "el profesional")
    assistant_name = appointment_data.get("assistant_name", "Asistente")

    instructions_text = f"\n\nIndicaciones:\n{instructions}" if instructions else ""

    if tone == "informal":
        return (
            f"¡Hola {patient_name}! 👋\n\n"
            f"Gracias por tu visita hoy. {professional_name} espera que te sientas mejor pronto.\n"
            f"{instructions_text}\n\n"
            f"Si tienes preguntas, cuéntanos. ¡Estamos aquí para ayudarte!\n\n"
            f"— {assistant_name}"
        )
    else:  # formal
        return (
            f"Estimado(a) {patient_name},\n\n"
            f"Agradecemos su visita el día de hoy. {professional_name} le desea una pronta recuperación.\n"
            f"{instructions_text}\n\n"
            f"Si tiene preguntas o inquietudes, no dude en contactarnos.\n\n"
            f"Atentamente,\n{assistant_name}"
        )


def appointment_confirmation(appointment_data: dict, tone: str = "formal") -> str:
    """
    Generate appointment confirmation message.

    Args:
        appointment_data: Appointment data
        tone: Message tone (formal|informal)

    Returns:
        Formatted confirmation message
    """
    patient_name = appointment_data.get("patient_name", "estimado cliente")
    date = appointment_data.get("date", "la fecha programada")
    time = appointment_data.get("time", "la hora programada")
    office_name = appointment_data.get("office_name", "nuestro consultorio")
    assistant_name = appointment_data.get("assistant_name", "Asistente")

    if tone == "informal":
        return (
            f"¡Perfecto, {patient_name}! ✅\n\n"
            f"Tu cita está confirmada:\n"
            f"📅 {date}\n"
            f"🕒 {time}\n"
            f"📍 {office_name}\n\n"
            f"¡Te esperamos! Si hay cambios, avísanos.\n\n"
            f"— {assistant_name}"
        )
    else:  # formal
        return (
            f"Estimado(a) {patient_name},\n\n"
            f"Confirmamos su cita:\n"
            f"Fecha: {date}\n"
            f"Hora: {time}\n"
            f"Lugar: {office_name}\n\n"
            f"Agradecemos su preferencia. Le esperamos.\n\n"
            f"Atentamente,\n{assistant_name}"
        )


def appointment_cancellation(appointment_data: dict, tone: str = "formal") -> str:
    """
    Generate appointment cancellation message.

    Args:
        appointment_data: Appointment data
        tone: Message tone (formal|informal)

    Returns:
        Formatted cancellation message
    """
    patient_name = appointment_data.get("patient_name", "estimado cliente")
    date = appointment_data.get("date", "la fecha programada")
    office_name = appointment_data.get("office_name", "nuestro consultorio")
    assistant_name = appointment_data.get("assistant_name", "Asistente")

    if tone == "informal":
        return (
            f"Entendido, {patient_name} 👍\n\n"
            f"Hemos cancelado tu cita del {date} en {office_name}.\n\n"
            f"Cuando estés listo, agendar de nuevo es muy fácil. ¡Cuéntanos!\n\n"
            f"— {assistant_name}"
        )
    else:  # formal
        return (
            f"Estimado(a) {patient_name},\n\n"
            f"Confirmamos la cancelación de su cita del {date} en {office_name}.\n\n"
            f"Cuando desee reagendar, estaremos disponibles para atenderlo(a).\n\n"
            f"Atentamente,\n{assistant_name}"
        )
