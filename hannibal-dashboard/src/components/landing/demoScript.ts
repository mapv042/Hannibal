export interface Turn {
  role: 'user' | 'assistant'
  content: string
}

export const GREETING =
  'Hola 👋 Soy Sofía, del Consultorio Dr. García. ¿En qué le puedo ayudar?'

/** Prompts offered as tappable chips under the greeting. */
export const SUGGESTIONS = [
  'Quiero agendar una cita',
  'Necesito cancelar mi cita',
  '¿Tienen lugar mañana?',
]

/** Free conversation ends here so the demo stays a demo. */
export const MAX_USER_MESSAGES = 8
/** After this many turns the doctor has seen enough to be asked to sign up. */
export const CTA_AFTER = 2

const norm = (s: string) =>
  s
    .toLowerCase()
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')

const has = (text: string, words: string[]) => words.some((w) => text.includes(w))

/**
 * Symptoms the real assistant escalates instead of booking. Worth showing in
 * the demo because it's the behaviour doctors are most sceptical about.
 */
const RED_FLAGS = [
  'no veo',
  'perdi la vista',
  'perdida de vision',
  'vision borrosa',
  'dolor de pecho',
  'sangrado',
  'sangre',
  'no puedo respirar',
  'dificultad para respirar',
  'desmay',
  'urgencia',
  'urgente',
  'emergencia',
]

/**
 * Produces Sofía's next line.
 *
 * TODO(demo-endpoint): today this resolves from a script so the public page
 * costs nothing and can't be prompt-injected. When `POST /api/demo/chat` exists
 * (public, rate-limited per IP, system prompt held server-side), this function
 * body is the only thing that changes:
 *
 *     const res = await fetch('/api/demo/chat', {
 *       method: 'POST',
 *       headers: { 'Content-Type': 'application/json' },
 *       body: JSON.stringify({ message: text, history }),
 *     })
 *     return (await res.json()).reply
 *
 * The copy in DemoSection must switch back to the live claim at the same time —
 * see the note there.
 */
export async function getDemoReply(text: string, history: Turn[]): Promise<string> {
  // The typing indicator only reads as real if the reply takes a moment.
  await new Promise((r) => setTimeout(r, 700 + Math.random() * 600))
  return scriptedReply(text, history)
}

function scriptedReply(text: string, history: Turn[]): string {
  const t = norm(text)
  const said = (words: string[]) =>
    history.some((h) => h.role === 'assistant' && has(norm(h.content), words))

  if (has(t, RED_FLAGS)) {
    return 'Eso no puede esperar a una cita normal. Voy a avisarle al Dr. García en este momento y le confirmo en cuanto responda 🙏'
  }

  if (has(t, ['cancel'])) {
    return 'Claro. Tengo su cita del jueves 25 a las 17:30. ¿Se la cancelo o prefiere que la mueva a otro día?'
  }

  if (has(t, ['mover', 'reagend', 'cambiar', 'otro dia', 'otra hora'])) {
    return 'Sin problema. Le puedo mover a viernes 26 a las 9:00 o lunes 29 a las 11:00. ¿Cuál le acomoda?'
  }

  if (has(t, ['costo', 'precio', 'cuanto cuesta', 'cuanto sale'])) {
    return 'La primera consulta son $800 y la subsecuente $600. ¿Le agendo una?'
  }

  if (has(t, ['seguro', 'aseguradora', 'gnp', 'axa'])) {
    return 'Sí manejamos seguro, con GNP y AXA. ¿Con cuál cuenta usted?'
  }

  if (has(t, ['donde', 'direccion', 'ubica'])) {
    return 'Estamos en Av. México 1234, Col. Americana, Guadalajara. ¿Le agendo una cita?'
  }

  // Picking a time — only meaningful once options were on the table.
  if (
    said(['tengo', 'le puedo', 'acomoda']) &&
    has(t, [
      'martes',
      'jueves',
      'viernes',
      'lunes',
      'miercoles',
      'primero',
      'segundo',
      'ese',
      'esa',
      'si',
      'ok',
      'va',
      'sale',
      '10',
      '11',
      '9',
      '4',
      '17',
    ])
  ) {
    return 'Listo ✓ Su cita quedó confirmada. Le mando un recordatorio un día antes y otro dos horas antes. ¿Necesita algo más?'
  }

  if (has(t, ['agendar', 'cita', 'consulta', 'espacio', 'lugar', 'manana', 'hoy'])) {
    return 'Con gusto. Tengo martes 10:00 o jueves 16:00. ¿Cuál le viene mejor?'
  }

  if (has(t, ['gracias', 'nada mas', 'es todo'])) {
    return 'A sus órdenes 🙏 Aquí estoy a cualquier hora que me necesite.'
  }

  if (has(t, ['quien eres', 'que eres', 'eres un bot', 'eres una ia', 'robot'])) {
    return 'Soy la asistente de WhatsApp del consultorio — contesto, agendo y le recuerdo sus citas. Funciono con ArgosAI 😊'
  }

  return 'Con gusto le ayudo. ¿Quiere agendar, cancelar o mover una cita?'
}

export const CLOSING_MESSAGE =
  'Espero haberle mostrado cómo funciono 🙏 Para seguir probando, actíveme en su propio consultorio — son 10 minutos.'
