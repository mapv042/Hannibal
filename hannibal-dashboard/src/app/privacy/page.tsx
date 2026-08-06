import type { Metadata } from 'next'
import { LegalLayout } from '@/components/legal/LegalLayout'

export const metadata: Metadata = {
  title: 'Aviso de privacidad · ArgosAI',
  description: 'Aviso de privacidad de ArgosAI, el asistente de WhatsApp para consultorios.',
}

export default function PrivacyPage() {
  return (
    <LegalLayout title="Aviso de privacidad" updated="3 de agosto de 2026">
      <p>
        Este aviso describe cómo <strong>ArgosAI</strong> (&quot;ArgosAI&quot;, &quot;nosotros&quot;), operado por{' '}
        Miguel Angel Partida Velasco, con domicilio en{' '}
        <strong>Guadalajara, Jalisco, México</strong>, recaba, usa y protege los datos personales de los doctores que
        contratan el servicio (&quot;el consultorio&quot;) y de los pacientes que interactúan con el asistente por
        WhatsApp, conforme a la Ley Federal de Protección de Datos Personales en Posesión de los Particulares
        (LFPDPPP).
      </p>

      <h2>1. Datos que recabamos</h2>
      <p>Dependiendo de si eres el doctor/consultorio o un paciente que escribe por WhatsApp, recabamos:</p>
      <ul>
        <li><strong>Del consultorio:</strong> nombre, correo, número de WhatsApp del negocio, horarios de atención, y — si conectas Google Calendar — los eventos y disponibilidad de tu calendario.</li>
        <li><strong>Del paciente:</strong> nombre, número de WhatsApp, e información que comparta en la conversación para agendar, confirmar o cancelar una cita (por ejemplo, motivo de consulta a nivel general).</li>
        <li><strong>Datos de salud:</strong> cuando un paciente describe síntomas para evaluar una urgencia, ese texto se considera dato personal sensible bajo la LFPDPPP y se trata con medidas de seguridad reforzadas.</li>
      </ul>

      <h2>2. Uso de los datos de Google (Google Calendar)</h2>
      <p>
        Si el consultorio conecta su cuenta de Google, ArgosAI accede únicamente a los eventos y disponibilidad
        de su Google Calendar para: mostrar los horarios libres a los pacientes, crear el evento correspondiente
        cuando se agenda una cita, y mantener el calendario sincronizado cuando una cita se reprograma o cancela.
      </p>
      <ul>
        <li>No usamos los datos de Google para publicidad ni los vendemos a terceros.</li>
        <li>No compartimos los datos de tu Google Calendar con nadie fuera de la operación del servicio.</li>
        <li>Puedes revocar el acceso en cualquier momento desde la configuración de tu cuenta de Google o desde el panel de ArgosAI; al hacerlo, dejamos de sincronizar tu calendario de inmediato.</li>
        <li>El uso que ArgosAI hace de la información recibida de las APIs de Google se apega a la <a href="https://developers.google.com/terms/api-services-user-data-policy" target="_blank" rel="noopener noreferrer">Política de Datos de Usuario de los Servicios de API de Google</a>, incluyendo los requisitos de Uso Limitado.</li>
      </ul>

      <h2>3. Finalidades del tratamiento</h2>
      <ul>
        <li>Agendar, confirmar, reprogramar y cancelar citas médicas.</li>
        <li>Enviar recordatorios de citas por WhatsApp.</li>
        <li>Detectar y escalar solicitudes de atención urgente al doctor.</li>
        <li>Mantener el historial de conversación necesario para dar continuidad a la atención.</li>
        <li>Facturación y administración de la cuenta del consultorio.</li>
      </ul>

      <h2>4. Con quién compartimos los datos</h2>
      <p>
        No vendemos datos personales. Compartimos la información estrictamente necesaria con los proveedores que
        hacen posible el servicio: Meta (envío de mensajes de WhatsApp), Google (Calendar, cuando el consultorio lo
        conecta), y nuestros proveedores de infraestructura (hosting y base de datos). Cada uno está obligado
        contractualmente a proteger la información y usarla solo para prestar su servicio a ArgosAI.
      </p>

      <h2>5. Dónde se almacenan los datos</h2>
      <p>
        Los datos se almacenan en bases de datos con controles de acceso y cifrado en tránsito y en reposo para
        la información sensible (por ejemplo, tokens de acceso a WhatsApp y Google Calendar).
      </p>

      <h2>6. Derechos ARCO</h2>
      <p>
        Como titular de tus datos, tienes derecho a Acceder, Rectificar, Cancelar u Oponerte (ARCO) al tratamiento
        de tu información, así como a revocar tu consentimiento. Para ejercer estos derechos, escríbenos a{' '}
        <strong>soporte@argosai.mx</strong>.
      </p>

      <h2>7. Cambios a este aviso</h2>
      <p>
        Si actualizamos este aviso de forma significativa, lo notificaremos al consultorio por correo o dentro del
        panel de control antes de que entre en vigor.
      </p>

      <h2>8. Contacto</h2>
      <p>
        Dudas sobre este aviso o sobre tus datos: <strong>soporte@argosai.mx</strong>.
      </p>
    </LegalLayout>
  )
}
