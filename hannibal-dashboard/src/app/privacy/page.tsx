import type { Metadata } from 'next'
import { LegalLayout } from '@/components/legal/LegalLayout'

export const metadata: Metadata = {
  title: 'Aviso de privacidad · ArgosAI',
  description: 'Aviso de privacidad de ArgosAI, el asistente de WhatsApp para consultorios.',
}

export default function PrivacyPage() {
  return (
    <LegalLayout title="Aviso de privacidad" updated="25 de agosto de 2026">
      <p>
        Este aviso describe cómo <strong>ArgosAI</strong> (&quot;ArgosAI&quot;, &quot;nosotros&quot;), operado por{' '}
        Miguel Angel Partida Velasco, con domicilio en{' '}
        <strong>Guadalajara, Jalisco, México</strong>, recaba, usa, comparte, protege y elimina los datos personales
        de los doctores que contratan el servicio (&quot;el consultorio&quot;) y de los pacientes que interactúan con
        el asistente por WhatsApp, conforme a la Ley Federal de Protección de Datos Personales en Posesión de los
        Particulares (LFPDPPP).
      </p>

      <h2>1. Datos que recabamos</h2>
      <p>Dependiendo de si eres el doctor/consultorio o un paciente que escribe por WhatsApp, recabamos:</p>
      <ul>
        <li><strong>Del consultorio:</strong> nombre, correo, número de WhatsApp del negocio, horarios de atención, y — si conectas Google Calendar — los eventos y disponibilidad de tu calendario.</li>
        <li><strong>Del paciente:</strong> nombre, número de WhatsApp, e información que comparta en la conversación para agendar, confirmar o cancelar una cita (por ejemplo, motivo de consulta a nivel general).</li>
        <li><strong>Datos personales sensibles:</strong> cuando un paciente describe síntomas o un motivo de consulta para evaluar una urgencia, ese texto se considera dato personal sensible de salud bajo la LFPDPPP. La sección 5 detalla las medidas específicas con las que lo protegemos.</li>
      </ul>
      <p>
        No pedimos ni necesitamos expedientes clínicos, resultados de estudios, diagnósticos formales, datos
        financieros del paciente ni datos de identificación oficial. El asistente está diseñado para agendar citas
        con la mínima información necesaria.
      </p>

      <h2>2. Uso de los datos de Google (Google Calendar)</h2>
      <p>
        Si el consultorio conecta su cuenta de Google, ArgosAI accede únicamente a los eventos y disponibilidad
        de su Google Calendar para: mostrar los horarios libres a los pacientes, crear el evento correspondiente
        cuando se agenda una cita, y mantener el calendario sincronizado cuando una cita se reprograma o cancela.
      </p>
      <ul>
        <li>No usamos los datos de Google para publicidad, ni los vendemos, rentamos o cedemos a terceros.</li>
        <li>No compartimos los datos de tu Google Calendar con nadie fuera de la operación del servicio.</li>
        <li><strong>No usamos los datos obtenidos de las APIs de Google Workspace —incluido Google Calendar— para desarrollar, mejorar o entrenar modelos generalizados de inteligencia artificial o aprendizaje automático</strong>, ni propios ni de terceros. Tampoco enviamos títulos, descripciones, invitados ni ningún otro contenido de tus eventos a nuestros proveedores de IA: la disponibilidad se calcula únicamente a partir de intervalos de tiempo ocupado/libre.</li>
        <li>Ningún ser humano lee el contenido de tu calendario, salvo que tú lo solicites expresamente para resolver un problema de soporte que reportes.</li>
        <li>Puedes revocar el acceso en cualquier momento desde la configuración de tu cuenta de Google o desde el panel de ArgosAI. Al desconectar, revocamos el token ante Google, lo borramos de nuestra base de datos, cancelamos los canales de notificación y eliminamos la copia sincronizada de tus eventos.</li>
        <li>El uso que ArgosAI hace de la información recibida de las APIs de Google se apega a la <a href="https://developers.google.com/terms/api-services-user-data-policy" target="_blank" rel="noopener noreferrer">Política de Datos de Usuario de los Servicios de API de Google</a>, incluyendo los requisitos de Uso Limitado (Limited Use).</li>
      </ul>

      <h2>3. Finalidades del tratamiento</h2>
      <ul>
        <li>Agendar, confirmar, reprogramar y cancelar citas médicas.</li>
        <li>Enviar recordatorios de citas por WhatsApp.</li>
        <li>Detectar y escalar solicitudes de atención urgente al doctor.</li>
        <li>Mantener el historial de conversación necesario para dar continuidad a la atención.</li>
        <li>Facturación y administración de la cuenta del consultorio.</li>
      </ul>
      <p>
        No usamos los datos para publicidad, no elaboramos perfiles comerciales y no los vendemos. Cualquier
        finalidad distinta a las anteriores requeriría tu consentimiento previo.
      </p>

      <h2>4. Cómo protegemos tus datos</h2>
      <p>
        Aplicamos medidas de seguridad administrativas, técnicas y físicas para proteger los datos personales
        contra pérdida, uso indebido, acceso no autorizado, divulgación, alteración o destrucción. En concreto:
      </p>
      <ul>
        <li><strong>Cifrado en tránsito:</strong> todo el tráfico entre tu navegador, el asistente de WhatsApp, nuestros servidores y las APIs de Google y Meta viaja sobre HTTPS/TLS 1.2 o superior. El panel web se sirve exclusivamente por HTTPS.</li>
        <li><strong>Cifrado en reposo:</strong> la base de datos y sus respaldos están cifrados en disco (AES-256) por nuestro proveedor de infraestructura.</li>
        <li><strong>Cifrado adicional a nivel de aplicación:</strong> las credenciales más sensibles —el token de acceso a WhatsApp y los tokens OAuth de Google Calendar— se guardan cifrados con una llave propia (Fernet, AES-128 en modo CBC con autenticación HMAC-SHA256) que vive fuera de la base de datos, de modo que ni siquiera un volcado de la base de datos las expone en texto claro.</li>
        <li><strong>Control de acceso y aislamiento por consultorio:</strong> el panel exige autenticación; cada petición se valida con un token firmado y toda consulta está acotada al consultorio dueño de los datos. Un consultorio no puede leer ni modificar la información de otro. La base de datos tiene además Row Level Security activado como control adicional.</li>
        <li><strong>Mínimo privilegio:</strong> solicitamos a Google únicamente los permisos indispensables para agendar y sincronizar citas, y los secretos de producción se administran como variables de entorno cifradas, no en el código fuente. El acceso a las consolas de infraestructura está limitado al operador del servicio y protegido con verificación en dos pasos.</li>
        <li><strong>Registros sin contenido personal:</strong> nuestros registros operativos guardan metadatos (identificadores, marcas de tiempo, resultado de la operación) y no el contenido de las conversaciones ni de los eventos de calendario.</li>
        <li><strong>Proveedores auditados:</strong> operamos sobre proveedores de infraestructura con certificaciones reconocidas (SOC 2 / ISO 27001) y contratos que los obligan a tratar los datos únicamente por cuenta nuestra.</li>
        <li><strong>Respaldos:</strong> los respaldos de la base de datos heredan el mismo cifrado en reposo y los mismos controles de acceso que los datos en producción.</li>
        <li><strong>Respuesta a incidentes:</strong> si ocurriera una vulneración que afecte de forma significativa tus datos, te lo notificaremos por correo sin demora injustificada, junto con el alcance y las medidas correctivas.</li>
      </ul>

      <h2>5. Datos sensibles de salud: medidas reforzadas</h2>
      <p>
        El texto en el que un paciente describe síntomas o un motivo de consulta recibe protección adicional a la
        descrita arriba:
      </p>
      <ul>
        <li><strong>Minimización:</strong> el asistente solo pide lo necesario para agendar o para que el doctor decida sobre una urgencia; no solicita historial clínico, estudios ni diagnósticos.</li>
        <li><strong>Acceso restringido:</strong> esta información es visible únicamente para el consultorio al que el paciente escribió. El personal de ArgosAI no accede a ella de forma rutinaria; solo puede hacerlo un administrador autorizado, de forma puntual, cuando es indispensable para resolver una falla reportada.</li>
        <li><strong>Sin entrenamiento de modelos:</strong> ni el contenido de las conversaciones ni los datos de salud se usan para entrenar, ajustar o mejorar modelos de inteligencia artificial. Contratamos a nuestros proveedores de IA bajo condiciones de uso empresarial que prohíben el entrenamiento con los datos enviados a través de la API.</li>
        <li><strong>Retención acotada:</strong> el contexto vivo de la conversación se guarda en memoria temporal con expiración automática a las 24 horas; solo persiste en la base de datos el historial de la cita y los mensajes necesarios para dar continuidad a la atención.</li>
        <li><strong>Consentimiento:</strong> el paciente comparte esta información de forma voluntaria en el chat; puede pedir su eliminación en cualquier momento por los medios de la sección 7.</li>
      </ul>

      <h2>6. Con quién compartimos los datos</h2>
      <p>
        No vendemos datos personales. Compartimos únicamente la información estrictamente necesaria con los
        encargados que hacen posible el servicio, todos obligados contractualmente a protegerla y a usarla solo
        para prestarnos su servicio:
      </p>
      <ul>
        <li><strong>Meta (WhatsApp Business Platform):</strong> envío y recepción de los mensajes.</li>
        <li><strong>Google:</strong> Google Calendar, únicamente cuando el consultorio conecta su cuenta.</li>
        <li><strong>Proveedores de infraestructura</strong> (hosting de la aplicación, base de datos administrada y caché): almacenamiento y ejecución del servicio.</li>
        <li><strong>Proveedor de modelos de lenguaje</strong> (OpenAI o Anthropic, según la configuración): procesa el texto del mensaje para redactar la respuesta del asistente, bajo condiciones que prohíben usar esos datos para entrenar modelos. <strong>Los datos provenientes de las APIs de Google no se envían a estos proveedores.</strong></li>
      </ul>
      <p>
        También podríamos divulgar información cuando la ley lo exija o para responder a un requerimiento válido de
        una autoridad competente.
      </p>

      <h2>7. Conservación y eliminación</h2>
      <ul>
        <li>Conservamos los datos del consultorio mientras la cuenta esté activa. Al cancelar el servicio, eliminamos o anonimizamos los datos personales dentro de los 90 días siguientes, salvo lo que la ley obligue a conservar (por ejemplo, comprobantes fiscales).</li>
        <li>El contexto de conversación en memoria temporal expira automáticamente a las 24 horas.</li>
        <li>Al desconectar Google Calendar, los tokens se revocan y se borran de inmediato, y se elimina la copia sincronizada de los eventos.</li>
        <li>Un paciente puede solicitar la eliminación de sus datos escribiendo a la dirección de la sección 8; atenderemos la solicitud en un plazo máximo de 20 días hábiles.</li>
      </ul>

      <h2>8. Derechos ARCO</h2>
      <p>
        Como titular de tus datos, tienes derecho a Acceder, Rectificar, Cancelar u Oponerte (ARCO) al tratamiento
        de tu información, así como a revocar tu consentimiento y a solicitar la eliminación de tus datos. Para
        ejercer estos derechos, escríbenos a <strong>soporte@argosai.mx</strong>.
      </p>

      <h2>9. Cambios a este aviso</h2>
      <p>
        Si actualizamos este aviso de forma significativa, lo notificaremos al consultorio por correo o dentro del
        panel de control antes de que entre en vigor.
      </p>

      <h2>10. Contacto</h2>
      <p>
        Dudas sobre este aviso, sobre tus datos o sobre nuestras medidas de seguridad:{' '}
        <strong>soporte@argosai.mx</strong>.
      </p>
    </LegalLayout>
  )
}
