"""Intent detection prompt for Claude."""

from __future__ import annotations

INTENT_DETECTION_PROMPT = """Analiza el siguiente mensaje de usuario y su historial de conversación para detectar su intención.

FECHA DE HOY: {today_date}
IMPORTANTE: Cuando el usuario mencione días de la semana (ej: "martes", "jueves"), calcula la fecha del próximo día más cercano usando la fecha de hoy como referencia. El año actual es {current_year}.

INTENCIONES POSIBLES:
- SCHEDULE: Quiere programar una nueva cita
- CANCEL: Quiere cancelar una cita existente
- RESCHEDULE: Quiere cambiar la fecha/hora de una cita
- CONFIRM: Quiere confirmar una cita programada
- QUESTION: Hace una pregunta general (horarios, ubicación, servicios, etc.)
- URGENT: Hay emergencia médica o situación urgente
- GREETING: Solo saluda o inicia conversación
- OTHER: No encaja en las categorías anteriores

RESPONDE EN FORMATO JSON con la siguiente estructura:
{{
  "intent": "SCHEDULE|CANCEL|RESCHEDULE|CONFIRM|QUESTION|URGENT|GREETING|OTHER",
  "confidence": 0.0-1.0,
  "extracted_data": {{
    "name": "nombre del paciente o null",
    "reason": "motivo de consulta o null",
    "proposed_date": "fecha en formato YYYY-MM-DD o null",
    "proposed_time": "hora en formato HH:MM o null",
    "appointment_number": "ID de cita si menciona cancelación/confirmación o null"
  }},
  "explanation": "breve explicación de por qué se detectó esta intención"
}}

PISTAS PARA DETECTAR INTENCIONES:
- SCHEDULE: palabras como "agendar", "cita", "quiero ir", "¿cuándo puedo?", "tengo que ir"
- CANCEL: "cancelar", "no puedo ir", "anular", "no vengo"
- RESCHEDULE: "cambiar", "otra fecha", "otro horario", "postergue"
- CONFIRM: "confirmo", "sí", "dale", respuesta positiva a propuesta
- QUESTION: "¿cuál es?", "¿a qué hora?", "¿dónde?", "información"
- URGENT: "emergencia", "dolor", "hospital", "ambulancia", "ahora", "ya"
- GREETING: "hola", "buenos días", "¿qué tal?"
- OTHER: mensajes ambiguos o no relacionados

CONTEXTO DE CONVERSACIÓN:
{conversation_history}

MENSAJE ACTUAL DEL USUARIO:
{user_message}

Responde SOLO el JSON, sin texto adicional."""
