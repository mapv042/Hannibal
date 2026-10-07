import type { Metadata } from 'next'
import { notFound } from 'next/navigation'
import { LegalLayout } from '@/components/legal/LegalLayout'

/**
 * The privacy notice of ONE practice — the page the WhatsApp consent question
 * links to. The practice is the data controller ("responsable"); Argos is the
 * processor ("encargado"). The text is a template filled with the office's own
 * data and must be reviewed by a lawyer before the product is sold; bump
 * PRIVACY_NOTICE_VERSION (backend, privacy/consent.py) whenever it changes
 * materially, so patients are asked again.
 */

interface NoticeData {
  office_name: string
  doctor_name: string | null
  address: string | null
  city: string | null
  state: string | null
  contact_email: string | null
  whatsapp_phone: string | null
  version: string
}

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

/** "5215559876543" → "+52 55 5987 6543" (Meta's ids carry a legacy "1"). */
function displayPhone(raw: string): string {
  const digits = raw.replace(/\D/g, '')
  const local = digits.startsWith('521') && digits.length === 13 ? digits.slice(3) : digits.slice(-10)
  if (local.length !== 10) return raw
  return `+52 ${local.slice(0, 2)} ${local.slice(2, 6)} ${local.slice(6)}`
}

async function loadNotice(officeId: string): Promise<NoticeData | null> {
  try {
    const res = await fetch(`${API_URL}/api/public/privacy-notice/${encodeURIComponent(officeId)}`, {
      next: { revalidate: 300 },
    })
    if (!res.ok) return null
    return (await res.json()) as NoticeData
  } catch {
    return null
  }
}

export async function generateMetadata({
  params,
}: {
  params: { officeId: string }
}): Promise<Metadata> {
  const notice = await loadNotice(params.officeId)
  return {
    title: notice ? `Aviso de privacidad · ${notice.office_name}` : 'Aviso de privacidad',
    robots: { index: false },
  }
}

export default async function OfficePrivacyNoticePage({
  params,
}: {
  params: { officeId: string }
}) {
  const notice = await loadNotice(params.officeId)
  if (!notice) notFound()

  const responsible = notice.doctor_name
    ? `${notice.doctor_name}, a través de ${notice.office_name}`
    : notice.office_name
  const place = [notice.address, notice.city, notice.state].filter(Boolean).join(', ')
  const contact = notice.contact_email
    ? `el correo ${notice.contact_email}`
    : notice.whatsapp_phone
      ? `el WhatsApp del consultorio (${displayPhone(notice.whatsapp_phone)})`
      : 'los medios de contacto del consultorio'

  return (
    <LegalLayout title={`Aviso de privacidad — ${notice.office_name}`} updated={`versión ${notice.version}`}>
      <h2>1. Quién es responsable de tus datos</h2>
      <p>
        <strong>{responsible}</strong>
        {place ? <>, con domicilio en {place},</> : ','} es responsable del tratamiento de los datos
        personales que compartes al escribir por WhatsApp para agendar, confirmar, cambiar o cancelar
        una cita, conforme a la Ley Federal de Protección de Datos Personales en Posesión de los
        Particulares.
      </p>

      <h2>2. Qué datos tratamos</h2>
      <ul>
        <li>Nombre y número de WhatsApp.</li>
        <li>
          Los datos de tus citas: fecha, hora, si asististe, y la información que compartas para
          agendarlas.
        </li>
        <li>
          <strong>Datos personales sensibles de salud:</strong> el motivo de consulta y las respuestas
          a las preguntas previas que el consultorio configure (por ejemplo, desde cuándo tienes una
          molestia). Solo se tratan si aceptas este aviso.
        </li>
      </ul>
      <p>
        No se integra aquí tu expediente clínico, ni diagnósticos, ni datos bancarios o de
        identificación oficial.
      </p>

      <h2>3. Para qué los usamos</h2>
      <ul>
        <li>Agendar, confirmar, cambiar o cancelar tus citas.</li>
        <li>Enviarte recordatorios y avisos sobre tus citas por WhatsApp.</li>
        <li>
          Que el doctor conozca el motivo de tu visita antes de la consulta y pueda atender una
          urgencia.
        </li>
      </ul>
      <p>No usamos tus datos para publicidad ni los vendemos.</p>

      <h2>4. Tu consentimiento</h2>
      <p>
        Antes de agendar, el asistente del consultorio te pregunta por WhatsApp si aceptas este aviso.
        Tu respuesta (&quot;Acepto&quot; o &quot;No acepto&quot;) queda registrada con la fecha y la
        versión del aviso. Si no aceptas, puedes agendar llamando directamente al consultorio. Puedes
        revocar tu consentimiento en cualquier momento por {contact}.
      </p>

      <h2>5. Con quién se comparten</h2>
      <p>
        El consultorio usa a <strong>Argos</strong> como plataforma para operar su asistente de
        WhatsApp; Argos trata tus datos solo por cuenta del consultorio y para los fines de este
        aviso. Los mensajes viajan por WhatsApp (Meta) y, si el consultorio lo conectó, las citas se
        anotan en su Google Calendar. No hay otras transferencias.
      </p>

      <h2>6. Cuánto tiempo se guardan</h2>
      <p>
        Los mensajes de WhatsApp se borran automáticamente a los 12 meses. Los datos de tus citas se
        conservan mientras seas paciente del consultorio o hasta que pidas su cancelación.
      </p>

      <h2>7. Tus derechos (ARCO)</h2>
      <p>
        Puedes pedir acceso, rectificación, cancelación u oposición al tratamiento de tus datos por{' '}
        {contact}. Te responderemos en los plazos que marca la ley.
      </p>

      <h2>8. Cambios a este aviso</h2>
      <p>
        Si este aviso cambia de forma importante, te volveremos a pedir tu consentimiento por WhatsApp
        antes de tu siguiente cita.
      </p>
    </LegalLayout>
  )
}
