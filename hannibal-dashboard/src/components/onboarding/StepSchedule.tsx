import React from 'react'
import { Card, CardBody } from '@/components/ui/Card'
import { Button } from '@/components/ui/Button'
import { StepHeader } from '@/components/onboarding/StepHeader'
import { Plus, X } from 'lucide-react'

export interface TimeBlock {
  startTime: string
  endTime: string
}

export interface ScheduleDay {
  dayOfWeek: number
  enabled: boolean
  blocks: TimeBlock[]
}

export type ReminderType = 'day_before' | '4h' | '1h' | 'at_time' | 'post_appointment'

/**
 * Reminder catalog shown in onboarding. The offset (minutes relative to the
 * appointment start, negative = before) is fixed here; the doctor only chooses
 * which reminders to enable. Must stay in sync with the backend defaults in
 * app/core/constants.py (DEFAULT_REMINDER_RULES).
 */
export const REMINDER_DEFS: {
  type: ReminderType
  label: string
  description: string
  offsetMinutes: number
}[] = [
  { type: 'day_before', label: 'Un día antes', description: 'Recordatorio el día previo a la cita', offsetMinutes: -1440 },
  { type: '4h', label: '4 horas antes', description: 'Recordatorio 4 horas antes de la cita', offsetMinutes: -240 },
  { type: '1h', label: '1 hora antes', description: 'Recordatorio 1 hora antes de la cita', offsetMinutes: -60 },
  { type: 'at_time', label: 'Aviso de llegada', description: 'A la hora de la cita le preguntamos al paciente si ya llegó y te avisamos', offsetMinutes: 0 },
  { type: 'post_appointment', label: 'Seguimiento post-consulta', description: 'Mensaje de seguimiento después de la cita', offsetMinutes: 120 },
]

export type ReminderToggles = Record<ReminderType, boolean>

export const DEFAULT_REMINDER_TOGGLES: ReminderToggles = {
  day_before: true,
  '4h': true,
  '1h': true,
  at_time: true,
  post_appointment: true,
}

/** Build the on/off toggles from a list of reminder rules returned by the API. */
export function reminderTogglesFromRules(
  rules?: { reminder_type: string; enabled: boolean }[]
): ReminderToggles {
  const toggles: ReminderToggles = { ...DEFAULT_REMINDER_TOGGLES }
  if (!rules) return toggles
  for (const rule of rules) {
    if (rule.reminder_type in toggles) {
      toggles[rule.reminder_type as ReminderType] = rule.enabled
    }
  }
  return toggles
}

/** Build the API payload (all reminders, with their fixed offsets) from toggles. */
export function rulesFromReminderToggles(
  toggles: ReminderToggles
): { reminder_type: ReminderType; offset_minutes: number; enabled: boolean }[] {
  return REMINDER_DEFS.map((def) => ({
    reminder_type: def.type,
    offset_minutes: def.offsetMinutes,
    enabled: toggles[def.type],
  }))
}

export interface ScheduleData {
  days: ScheduleDay[]
  appointmentDuration: number
  newPatientDuration: number
  returningPatientDuration: number
  bufferMinutes: number
  reminders: ReminderToggles
}

interface StepScheduleProps {
  data: ScheduleData
  onUpdate: (data: Partial<ScheduleData>) => void
  onNext: () => void
  onBack: () => void
  loading?: boolean
}

const DAY_NAMES = ['Domingo', 'Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado']

export const StepSchedule: React.FC<StepScheduleProps> = ({
  data,
  onUpdate,
  onNext,
  onBack,
  loading,
}) => {
  const toggleDay = (dayOfWeek: number) => {
    const newDays = data.days.map((d) =>
      d.dayOfWeek === dayOfWeek
        ? {
            ...d,
            enabled: !d.enabled,
            blocks: !d.enabled && d.blocks.length === 0
              ? [{ startTime: '09:00', endTime: '17:00' }]
              : d.blocks,
          }
        : d
    )
    onUpdate({ days: newDays })
  }

  const updateBlock = (dayOfWeek: number, blockIndex: number, field: keyof TimeBlock, value: string) => {
    const newDays = data.days.map((d) =>
      d.dayOfWeek === dayOfWeek
        ? {
            ...d,
            blocks: d.blocks.map((b, i) =>
              i === blockIndex ? { ...b, [field]: value } : b
            ),
          }
        : d
    )
    onUpdate({ days: newDays })
  }

  const addBlock = (dayOfWeek: number) => {
    const newDays = data.days.map((d) =>
      d.dayOfWeek === dayOfWeek
        ? { ...d, blocks: [...d.blocks, { startTime: '14:00', endTime: '18:00' }] }
        : d
    )
    onUpdate({ days: newDays })
  }

  const removeBlock = (dayOfWeek: number, blockIndex: number) => {
    const newDays = data.days.map((d) =>
      d.dayOfWeek === dayOfWeek
        ? { ...d, blocks: d.blocks.filter((_, i) => i !== blockIndex) }
        : d
    )
    onUpdate({ days: newDays })
  }

  const toggleReminder = (type: ReminderType) => {
    onUpdate({ reminders: { ...data.reminders, [type]: !data.reminders[type] } })
  }

  const hasAtLeastOneDay = data.days.some((d) => d.enabled && d.blocks.length > 0)

  return (
    <Card>
      <CardBody className="space-y-4 p-8">
        <StepHeader
          eyebrow="Paso 2"
          title="¿Cuándo estás disponible?"
          subtitle="Define los horarios en los que tomas pacientes. El asistente solo ofrecerá citas dentro de estos bloques."
        />
        {/* Days */}
        <div className="space-y-2.5">
          {data.days.map((day) => (
            <div
              key={day.dayOfWeek}
              className={`p-4 rounded-lg border transition-colors ${
                day.enabled
                  ? 'border-line bg-white'
                  : 'border-line bg-off-white'
              }`}
            >
              <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
                <button
                  type="button"
                  onClick={() => toggleDay(day.dayOfWeek)}
                  className={`w-5 h-5 rounded-sm flex items-center justify-center border transition-colors flex-shrink-0 ${
                    day.enabled
                      ? 'bg-accent border-accent text-white'
                      : 'bg-white border-slate-light'
                  }`}
                >
                  {day.enabled && (
                    <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={3} d="M5 13l4 4L19 7" />
                    </svg>
                  )}
                </button>
                <span className={`text-sm font-medium w-24 ${day.enabled ? 'text-navy' : 'text-slate-light'}`}>
                  {DAY_NAMES[day.dayOfWeek]}
                </span>

                {day.enabled && (
                  <div className="basis-full sm:basis-auto sm:flex-1 space-y-2">
                    {day.blocks.map((block, bi) => (
                      <div key={bi} className="flex items-center gap-2">
                        <input
                          type="time"
                          value={block.startTime}
                          onChange={(e) => updateBlock(day.dayOfWeek, bi, 'startTime', e.target.value)}
                          className="input-field py-1.5 px-2 text-sm flex-1 min-w-0 sm:flex-none sm:w-28"
                        />
                        <span className="text-slate-light text-sm flex-shrink-0">a</span>
                        <input
                          type="time"
                          value={block.endTime}
                          onChange={(e) => updateBlock(day.dayOfWeek, bi, 'endTime', e.target.value)}
                          className="input-field py-1.5 px-2 text-sm flex-1 min-w-0 sm:flex-none sm:w-28"
                        />
                        {day.blocks.length > 1 && (
                          <button
                            type="button"
                            onClick={() => removeBlock(day.dayOfWeek, bi)}
                            className="p-1 text-slate-light hover:text-red-500 transition-colors"
                          >
                            <X size={16} />
                          </button>
                        )}
                      </div>
                    ))}
                    <button
                      type="button"
                      onClick={() => addBlock(day.dayOfWeek)}
                      className="flex items-center gap-1 text-xs text-accent hover:text-accent-bright transition-colors"
                    >
                      <Plus size={14} />
                      Agregar bloque
                    </button>
                  </div>
                )}
              </div>
            </div>
          ))}
        </div>

        {/* Duration & Buffer */}
        <div className="space-y-3 p-5 bg-off-white border border-line rounded-xl">
          <p className="text-sm font-semibold text-navy">Duración de citas</p>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div className="flex flex-col">
              <label className="block text-sm font-medium text-slate mb-1.5">
                Duración primera consulta
              </label>
              <select
                value={data.newPatientDuration}
                onChange={(e) => {
                  const val = Number(e.target.value)
                  onUpdate({
                    newPatientDuration: val,
                    appointmentDuration: Math.max(val, data.returningPatientDuration),
                  })
                }}
                className="input-field mt-auto"
              >
                <option value={15}>15 minutos</option>
                <option value={20}>20 minutos</option>
                <option value={30}>30 minutos</option>
                <option value={45}>45 minutos</option>
                <option value={60}>60 minutos</option>
                <option value={90}>90 minutos</option>
              </select>
            </div>
            <div className="flex flex-col">
              <label className="block text-sm font-medium text-slate mb-1.5">
                Duración consulta subsecuente
              </label>
              <select
                value={data.returningPatientDuration}
                onChange={(e) => {
                  const val = Number(e.target.value)
                  onUpdate({
                    returningPatientDuration: val,
                    appointmentDuration: Math.max(data.newPatientDuration, val),
                  })
                }}
                className="input-field mt-auto"
              >
                <option value={15}>15 minutos</option>
                <option value={20}>20 minutos</option>
                <option value={30}>30 minutos</option>
                <option value={45}>45 minutos</option>
                <option value={60}>60 minutos</option>
                <option value={90}>90 minutos</option>
              </select>
            </div>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div className="flex flex-col">
              <label className="block text-sm font-medium text-slate mb-1.5">
                Descanso entre citas
              </label>
              <select
                value={data.bufferMinutes}
                onChange={(e) => onUpdate({ bufferMinutes: Number(e.target.value) })}
                className="input-field"
              >
                <option value={0}>Sin descanso</option>
                <option value={5}>5 minutos</option>
                <option value={10}>10 minutos</option>
                <option value={15}>15 minutos</option>
                <option value={20}>20 minutos</option>
              </select>
            </div>
          </div>
        </div>

        {/* Reminders */}
        <div className="space-y-3 p-5 bg-off-white border border-line rounded-xl">
          <div>
            <p className="text-sm font-semibold text-navy">Recordatorios automáticos</p>
            <p className="text-xs text-slate-light mt-0.5">
              Elige qué recordatorios enviará el asistente por WhatsApp a tus pacientes.
            </p>
          </div>
          <div className="space-y-2">
            {REMINDER_DEFS.map((reminder) => {
              const enabled = data.reminders[reminder.type]
              return (
                <button
                  key={reminder.type}
                  type="button"
                  onClick={() => toggleReminder(reminder.type)}
                  className={`w-full flex items-center gap-3 p-3 rounded-lg border text-left transition-colors ${
                    enabled ? 'border-primary-200 bg-primary-50' : 'border-line bg-white hover:border-slate-light'
                  }`}
                >
                  <span
                    className={`w-6 h-6 rounded flex items-center justify-center border-2 transition-colors flex-shrink-0 ${
                      enabled ? 'bg-accent border-accent text-white' : 'bg-white border-line'
                    }`}
                  >
                    {enabled && (
                      <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={3} d="M5 13l4 4L19 7" />
                      </svg>
                    )}
                  </span>
                  <span>
                    <span className={`block text-sm font-medium ${enabled ? 'text-navy' : 'text-slate-light'}`}>
                      {reminder.label}
                    </span>
                    <span className="block text-xs text-slate-light">{reminder.description}</span>
                  </span>
                </button>
              )
            })}
          </div>
        </div>

        <div className="flex gap-3 pt-2">
          <Button variant="secondary" onClick={onBack}>
            Atrás
          </Button>
          <Button
            onClick={onNext}
            disabled={!hasAtLeastOneDay}
            isLoading={loading}
            className="flex-1"
          >
            Continuar
          </Button>
        </div>
      </CardBody>
    </Card>
  )
}
