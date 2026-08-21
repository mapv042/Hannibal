import React from 'react'
import { Sparkles, Clock, AlertCircle } from 'lucide-react'
import { Badge } from '@/components/ui/Badge'
import type { ScheduleDay } from '@/components/onboarding/StepSchedule'

// ─── Shell ──────────────────────────────────────────────────────────────
interface PreviewPaneProps {
  title: string
  children: React.ReactNode
}

export const PreviewPane: React.FC<PreviewPaneProps> = ({ title, children }) => {
  return (
    <div
      className="rounded-xl border border-line bg-off-white p-7"
    >
      <div className="flex items-center gap-2 mb-6">
        <Sparkles size={13} className="text-accent" />
        <span className="eyebrow">{title}</span>
      </div>
      <div>{children}</div>
    </div>
  )
}

// ─── Helpers ──────────────────────────────────────────────────────────────
const MON_FIRST_ORDER = [1, 2, 3, 4, 5, 6, 0] // dayOfWeek values, Mon→Sun
const DAY_LABELS = ['Lun', 'Mar', 'Mié', 'Jue', 'Vie', 'Sáb', 'Dom']

function toHours(time: string): number {
  const [h, m] = time.split(':').map(Number)
  return h + m / 60
}

function dayWeeklyHours(day: ScheduleDay): number {
  if (!day.enabled) return 0
  return day.blocks.reduce(
    (sum, b) => sum + (toHours(b.endTime) - toHours(b.startTime)),
    0
  )
}

// ─── Schedule preview — mini weekly grid ────────────────────────────────
interface SchedulePreviewProps {
  days: ScheduleDay[]
  newPatientDuration: number
  returningPatientDuration: number
  bufferMinutes: number
}

export const SchedulePreview: React.FC<SchedulePreviewProps> = ({
  days,
  newPatientDuration,
  returningPatientDuration,
  bufferMinutes,
}) => {
  const byDow = new Map(days.map((d) => [d.dayOfWeek, d]))
  const ordered = MON_FIRST_ORDER.map((dow) => byDow.get(dow))
  const hours = Array.from({ length: 13 }, (_, i) => i + 8) // 08–20

  const enabledCount = days.filter((d) => d.enabled).length
  const totalHours = days.reduce((acc, d) => acc + dayWeeklyHours(d), 0)

  return (
    <div>
      <h3 className="display text-[22px] mb-1">Tu semana</h3>
      <p className="text-sm text-slate mb-5">Vista previa de tu disponibilidad</p>

      <div className="bg-white rounded-lg border border-line p-4">
        <div className="grid gap-0.5" style={{ gridTemplateColumns: '34px repeat(7, 1fr)' }}>
          <div />
          {DAY_LABELS.map((dn, i) => (
            <div
              key={dn}
              className={`text-[11px] font-semibold text-center pb-1.5 ${
                ordered[i]?.enabled ? 'text-slate' : 'text-slate-light'
              }`}
            >
              {dn}
            </div>
          ))}
          {hours.map((h) => (
            <React.Fragment key={h}>
              <div className="text-[10px] text-slate-light text-right pr-1">
                {h.toString().padStart(2, '0')}
              </div>
              {ordered.map((day, di) => {
                const isOn = !!day?.enabled
                const inBlock =
                  isOn &&
                  day!.blocks.some((b) => {
                    const start = toHours(b.startTime)
                    const end = toHours(b.endTime)
                    return h + 0.5 >= start && h + 0.5 < end
                  })
                return (
                  <div
                    key={di}
                    className="h-4 rounded-[3px]"
                    style={{
                      background: inBlock
                        ? '#2952A3'
                        : isOn
                        ? '#F7F9FC'
                        : 'repeating-linear-gradient(45deg, #EEF2F8, #EEF2F8 3px, transparent 3px, transparent 6px)',
                    }}
                  />
                )
              })}
            </React.Fragment>
          ))}
        </div>
      </div>

      <div className="grid grid-cols-3 gap-2 mt-4">
        <MiniStat label="Primera consulta" value={`${newPatientDuration} min`} />
        <MiniStat label="Subsecuente" value={`${returningPatientDuration} min`} />
        <MiniStat label="Descanso" value={`${bufferMinutes} min`} />
      </div>

      <div
        className="mt-4 p-3 rounded-lg border border-line bg-white flex items-center gap-2.5 text-[13px] text-slate"
      >
        <Clock size={16} className="text-accent flex-shrink-0" />
        <span>
          <b>{enabledCount} días</b> activos esta semana ·{' '}
          <b>{totalHours.toFixed(1)} hrs</b> totales
        </span>
      </div>
    </div>
  )
}

function MiniStat({ label, value }: { label: string; value: string }) {
  return (
    <div className="bg-white rounded-md border border-line px-3 py-2.5">
      <div className="text-[11px] text-slate-light mb-1">{label}</div>
      <div className="text-sm font-bold text-navy">{value}</div>
    </div>
  )
}

// ─── WhatsApp bubble primitives ─────────────────────────────────────────
function BotBubble({ children, time }: { children: React.ReactNode; time: string }) {
  return (
    <div
      className="bg-white text-[#0b141a] text-sm leading-snug px-3 py-2.5 rounded-lg rounded-tl-none shadow-[0_1px_0.5px_rgba(0,0,0,.13)]"
      style={{ maxWidth: '88%', whiteSpace: 'pre-wrap' }}
    >
      {children}
      <div className="text-right text-[11px] text-[#667781] mt-1">{time} ✓✓</div>
    </div>
  )
}

function PatientBubble({ children, time }: { children: React.ReactNode; time: string }) {
  return (
    <div
      className="bg-[#D9FDD3] text-[#0b141a] text-sm leading-snug px-3 py-2.5 rounded-lg rounded-tr-none shadow-[0_1px_0.5px_rgba(0,0,0,.13)] ml-auto"
      style={{ maxWidth: '70%' }}
    >
      {children}
      <div className="text-right text-[11px] text-[#667781] mt-1">{time}</div>
    </div>
  )
}

// ─── Pricing preview ────────────────────────────────────────────────────
interface ConsultationPreviewProps {
  first: string
  sub: string
  insurance: string
  insurances: string
}

export const ConsultationPreview: React.FC<ConsultationPreviewProps> = ({
  first,
  sub,
  insurance,
  insurances,
}) => {
  return (
    <div>
      <h3 className="display text-[22px] mb-1">
        Cómo se ve en WhatsApp
      </h3>
      <p className="text-sm text-slate mb-5">
        Esto es lo que el asistente le dirá a tus pacientes.
      </p>

      <div className="bg-[#ECE5DD] rounded-lg p-4">
        <BotBubble time="14:32">
          Claro, te comparto la información:
          <br />
          <br />
          <b>Primera consulta:</b> {first || '$—'}
          <br />
          <b>Consulta subsecuente:</b> {sub || '$—'}
          <br />
          <br />
          {insurance === 'No' && 'No aceptamos seguros médicos. El pago es directo.'}
          {insurance === 'Si' &&
            `Aceptamos seguros médicos.${insurances ? ` Trabajamos con: ${insurances}` : ''}`}
          {insurance === 'Algunos' &&
            `Aceptamos algunos seguros.${insurances ? ` Específicamente: ${insurances}` : ''}`}
          {!insurance && '¿Tienes alguna duda sobre el costo?'}
        </BotBubble>
      </div>

      <div
        className="mt-4 p-3.5 rounded-xl flex gap-2.5 text-[13px] text-slate leading-relaxed"
        style={{ background: 'rgba(14,165,233,.06)', border: '1px solid rgba(14,165,233,.18)' }}
      >
        <AlertCircle size={16} className="text-info flex-shrink-0 mt-0.5" />
        <span>
          El asistente solo comparte el precio cuando el paciente lo pregunta directamente.
          No insiste ni presiona la venta.
        </span>
      </div>
    </div>
  )
}

// ─── Assistant personality preview ──────────────────────────────────────
interface AssistantPreviewProps {
  name: string
  tone: 'formal' | 'informal'
  welcome: string
}

export const AssistantPreview: React.FC<AssistantPreviewProps> = ({
  name,
  tone,
  welcome,
}) => {
  const displayName = name || 'Sofía'
  const isCasual = tone === 'informal'
  const greeting = isCasual
    ? `Hola, soy ${displayName}, te ayudo con tu cita.`
    : `Hola, le saluda ${displayName}. ¿En qué le puedo ayudar?`

  return (
    <div>
      <h3 className="display text-[22px] mb-1">
        Conoce a {name || 'tu asistente'}
      </h3>
      <p className="text-sm text-slate mb-5">Así sonará en las conversaciones reales.</p>

      <div className="bg-[#ECE5DD] rounded-lg p-3.5 space-y-2">
        <BotBubble time="9:00">{welcome || greeting}</BotBubble>
        <PatientBubble time="9:01">
          {isCasual ? 'Hola, ¿tienes algo el viernes?' : 'Buen día, ¿tiene espacio el viernes?'}
        </PatientBubble>
        <BotBubble time="9:01">
          {isCasual
            ? '¡Sí! Te puedo ofrecer viernes a las 10:00 o 16:30. ¿Cuál te acomoda?'
            : 'Sí, le puedo ofrecer el viernes a las 10:00 o 16:30. ¿Cuál horario le acomoda?'}
        </BotBubble>
      </div>

      <div className="mt-4 p-3.5 rounded-lg bg-white border border-line flex items-center gap-3">
        <div
          className="w-10 h-10 rounded-full text-white flex items-center justify-center font-bold text-base flex-shrink-0"
          style={{ background: '#2952A3' }}
        >
          {displayName[0]?.toUpperCase()}
        </div>
        <div className="flex-1 min-w-0">
          <div className="text-sm font-semibold text-navy">{displayName}</div>
          <div className="text-xs text-slate-light">
            Tono: <b>{isCasual ? 'De tú · cercano' : 'De usted · formal'}</b>
          </div>
        </div>
        <Badge variant="success" dot>activo</Badge>
      </div>
    </div>
  )
}
