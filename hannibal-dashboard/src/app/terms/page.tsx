import type { Metadata } from 'next'
import { LegalLayout } from '@/components/legal/LegalLayout'

export const metadata: Metadata = {
  title: 'Términos de servicio · Hannibal',
  description: 'Términos de servicio de Hannibal, el asistente de WhatsApp para consultorios.',
}

export default function TermsPage() {
  return (
    <LegalLayout title="Términos de servicio" updated="3 de agosto de 2026">
      <p>
        Estos términos rigen el uso de Hannibal (&quot;el servicio&quot;), operado por{' '}
        <strong>Miguel Ángel Partida Velasco</strong>. Al crear una cuenta o usar el servicio, aceptas
        estos términos.
      </p>

      <h2>1. Qué es el servicio</h2>
      <p>
        Hannibal es un asistente automatizado que opera por WhatsApp para agendar, confirmar, recordar y cancelar
        citas de un consultorio médico o de salud, y un panel web para administrar esa configuración.
      </p>

      <h2>2. Cuenta del consultorio</h2>
      <ul>
        <li>Eres responsable de la exactitud de la información de tu consultorio (horarios, precios, datos de contacto) que el asistente usa para responder a tus pacientes.</li>
        <li>Eres responsable de mantener segura tu contraseña y el acceso a tu cuenta de Google conectada.</li>
        <li>El servicio no sustituye tu criterio médico: las urgencias detectadas por el asistente siempre requieren tu confirmación antes de agendarse.</li>
      </ul>

      <h2>3. Suscripción y pagos</h2>
      <p>
        El servicio se factura mensualmente según el plan vigente publicado en el sitio. Puedes cancelar en
        cualquier momento; la cancelación aplica al final del periodo ya pagado.
      </p>

      <h2>4. Uso aceptable</h2>
      <p>No puedes usar Hannibal para:</p>
      <ul>
        <li>Enviar mensajes masivos no solicitados (spam) a través del WhatsApp conectado.</li>
        <li>Suplantar a otra persona o negocio.</li>
        <li>Intentar vulnerar la seguridad de la plataforma o acceder a datos de otro consultorio.</li>
      </ul>

      <h2>5. Disponibilidad del servicio</h2>
      <p>
        Hacemos nuestro mejor esfuerzo para mantener el servicio disponible de forma continua, pero no
        garantizamos disponibilidad ininterrumpida. Recomendamos siempre tener un método alterno para emergencias
        médicas reales de tus pacientes.
      </p>

      <h2>6. Terminación</h2>
      <p>
        Podemos suspender o cancelar una cuenta que incumpla estos términos o que ponga en riesgo la operación del
        servicio para otros consultorios. Puedes cancelar tu cuenta cuando quieras desde el panel o escribiéndonos.
      </p>

      <h2>7. Límite de responsabilidad</h2>
      <p>
        El servicio se ofrece &quot;tal cual&quot;. En la medida permitida por la ley, no somos responsables por
        decisiones clínicas tomadas con base en la información gestionada por el asistente — la responsabilidad
        médica es siempre del profesional de salud.
      </p>

      <h2>8. Ley aplicable</h2>
      <p>
        Estos términos se rigen por las leyes de los Estados Unidos Mexicanos.
      </p>

      <h2>9. Contacto</h2>
      <p>
        Preguntas sobre estos términos: <strong>soporte@argosai.mx</strong>.
      </p>
    </LegalLayout>
  )
}
