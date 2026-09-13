import React from 'react'
import { Card, CardBody } from '@/components/ui/Card'
import { Button } from '@/components/ui/Button'
import { Input } from '@/components/ui/Input'
import { FieldError } from '@/components/ui/FieldError'
import { StepHeader } from '@/components/onboarding/StepHeader'
import { Lock, Plus, X } from 'lucide-react'
import { ASSISTANT_GENDERS, type CatalogOption } from '@/lib/constants/catalogs'
import type { FieldErrors } from '@/lib/validation/onboarding'

export interface PersonalizeData {
  assistantName: string
  assistantTone: 'formal' | 'informal'
  assistantGender: string
  /** Alarm symptoms, as plain strings (catalogue suggestions + the doctor's own). */
  emergencySymptoms: string[]
  /** Ids from the intake catalogue. */
  intakeQuestions: string[]
  /** One extra question specific to this practice. */
  intakeCustom: string
  notifyNewAppointment: boolean
  notifyCancellation: boolean
  notifyNewPatient: boolean
  notifyUnconfirmed: boolean
  notifyArrival: boolean
}

type NotifKey =
  | 'notifyNewAppointment'
  | 'notifyCancellation'
  | 'notifyNewPatient'
  | 'notifyUnconfirmed'
  | 'notifyArrival'

const NOTIFICATION_DEFS: { key: NotifKey; label: string; description: string }[] = [
  { key: 'notifyNewAppointment', label: 'Cita nueva agendada', description: 'Cuando el asistente agenda una cita.' },
  { key: 'notifyCancellation', label: 'Cancelación de paciente', description: 'Cuando un paciente cancela su cita.' },
  { key: 'notifyNewPatient', label: 'Paciente nuevo', description: 'Cuando se registra un paciente nuevo.' },
  { key: 'notifyUnconfirmed', label: 'Citas sin confirmar', description: 'Resumen al inicio del día con las citas de hoy sin confirmar.' },
  { key: 'notifyArrival', label: 'Check-in de llegada', description: 'Cuando el paciente avisa que ya llegó o que viene en camino.' },
]

interface StepPersonalizeProps {
  data: PersonalizeData
  onUpdate: (data: Partial<PersonalizeData>) => void
  onNext: () => void
  onBack: () => void
  loading?: boolean
  errors?: FieldErrors
  /** Suggested alarm symptoms for the chosen specialty. */
  suggestedSymptoms?: string[]
  intakeCatalog?: CatalogOption[]
}

const Checkbox = ({ checked }: { checked: boolean }) => (
  <span
    className={`w-5 h-5 rounded-sm flex items-center justify-center border transition-colors flex-shrink-0 ${
      checked ? 'bg-accent border-accent text-white' : 'bg-white border-slate-light'
    }`}
  >
    {checked && (
      <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={3} d="M5 13l4 4L19 7" />
      </svg>
    )}
  </span>
)

export const StepPersonalize: React.FC<StepPersonalizeProps> = ({
  data,
  onUpdate,
  onNext,
  onBack,
  loading,
  errors = {},
  suggestedSymptoms = [],
  intakeCatalog = [],
}) => {
  const toggleSymptom = (symptom: string) => {
    onUpdate({
      emergencySymptoms: data.emergencySymptoms.includes(symptom)
        ? data.emergencySymptoms.filter((s) => s !== symptom)
        : [...data.emergencySymptoms, symptom],
    })
  }

  const toggleIntake = (id: string) => {
    onUpdate({
      intakeQuestions: data.intakeQuestions.includes(id)
        ? data.intakeQuestions.filter((q) => q !== id)
        : [...data.intakeQuestions, id],
    })
  }

  // Symptoms the doctor added themselves, outside the specialty catalogue.
  const customSymptoms = data.emergencySymptoms.filter((s) => !suggestedSymptoms.includes(s))

  const addCustomSymptom = () => {
    onUpdate({ emergencySymptoms: [...data.emergencySymptoms, ''] })
  }

  const updateCustomSymptom = (value: string, position: number) => {
    let seen = -1
    onUpdate({
      emergencySymptoms: data.emergencySymptoms.map((s) => {
        if (suggestedSymptoms.includes(s)) return s
        seen += 1
        return seen === position ? value : s
      }),
    })
  }

  const removeCustomSymptom = (position: number) => {
    let seen = -1
    onUpdate({
      emergencySymptoms: data.emergencySymptoms.filter((s) => {
        if (suggestedSymptoms.includes(s)) return true
        seen += 1
        return seen !== position
      }),
    })
  }

  return (
    <Card>
      <CardBody className="space-y-6 p-8">
        <StepHeader
          eyebrow="Paso 4"
          title="Personaliza a tu asistente"
          subtitle="Decide cómo se llama, cómo habla y qué considera una emergencia."
        />

        <Input
          label="Nombre del asistente"
          placeholder="Sofía"
          value={data.assistantName}
          onChange={(e) => onUpdate({ assistantName: e.target.value })}
          error={errors.assistantName}
          helpText="Este nombre aparecerá en los mensajes a pacientes"
          data-field="assistantName"
        />

        <div>
          <label className="block text-sm font-semibold text-navy mb-2.5">
            Tono de conversación
          </label>
          <div className="grid grid-cols-2 gap-2.5">
            {[
              { value: 'formal' as const, label: 'De usted', desc: 'Formal, profesional', example: '«Buen día, ¿en qué le puedo ayudar?»' },
              { value: 'informal' as const, label: 'De tú', desc: 'Cercano, casual', example: '«¡Hola! ¿En qué te ayudo?»' },
            ].map((option) => {
              const active = data.assistantTone === option.value
              return (
                <button
                  key={option.value}
                  type="button"
                  onClick={() => onUpdate({ assistantTone: option.value })}
                  className={`choice-card ${active ? 'selected' : ''}`}
                >
                  <p className="text-[15px] font-semibold text-navy">{option.label}</p>
                  <p className="text-xs text-slate-light mt-0.5 mb-2.5">{option.desc}</p>
                  <p className="text-[12.5px] italic px-2.5 py-2 rounded-md bg-off-white text-slate">
                    {option.example}
                  </p>
                </button>
              )
            })}
          </div>
          <FieldError message={errors.assistantTone} />
        </div>

        <div>
          <label className="block text-sm font-semibold text-navy mb-1">
            ¿Cómo debe hablar de sí mismo?
          </label>
          <p className="text-xs text-slate-light mb-2.5">
            Para que concuerde bien al referirse a sí mismo, según el nombre que le pusiste.
          </p>
          <div className="grid grid-cols-3 gap-2.5">
            {ASSISTANT_GENDERS.map((option) => {
              const active = data.assistantGender === option.id
              return (
                <button
                  key={option.id}
                  type="button"
                  onClick={() => onUpdate({ assistantGender: option.id })}
                  className={`choice-card ${active ? 'selected' : ''}`}
                  data-field="assistantGender"
                >
                  <p className="text-[15px] font-semibold text-navy">{option.label}</p>
                  <p className="text-[12px] text-slate-light mt-0.5">{option.description}</p>
                </button>
              )
            })}
          </div>
          <FieldError message={errors.assistantGender} />
        </div>

        <div>
          <label className="block text-sm font-semibold text-navy mb-1">
            Síntomas de alarma
          </label>
          <p className="text-xs text-slate-light mb-2.5">
            Si un paciente menciona alguno, tu asistente te avisa de inmediato en vez de
            solo agendarlo. Te sugerimos los típicos de tu especialidad — ajústalos.
          </p>
          <div className="space-y-2">
            {suggestedSymptoms.map((symptom) => {
              const selected = data.emergencySymptoms.includes(symptom)
              return (
                <button
                  key={symptom}
                  type="button"
                  onClick={() => toggleSymptom(symptom)}
                  aria-pressed={selected}
                  className={`w-full flex items-center gap-3 p-2.5 rounded-lg border text-left transition-colors ${
                    selected ? 'border-primary-200 bg-primary-50' : 'border-line bg-white hover:border-slate-light'
                  }`}
                >
                  <Checkbox checked={selected} />
                  <span className={`text-sm ${selected ? 'text-navy' : 'text-slate'}`}>{symptom}</span>
                </button>
              )
            })}
          </div>

          {customSymptoms.length > 0 && (
            <div className="space-y-2 mt-2">
              {customSymptoms.map((symptom, position) => (
                <div key={position} className="flex items-center gap-2">
                  <input
                    type="text"
                    placeholder="Otro síntoma de alarma"
                    value={symptom}
                    onChange={(e) => updateCustomSymptom(e.target.value, position)}
                    className="input-field flex-1"
                    aria-label="Síntoma de alarma"
                  />
                  <button
                    type="button"
                    onClick={() => removeCustomSymptom(position)}
                    className="text-slate-light hover:text-error p-1"
                    aria-label="Quitar síntoma"
                  >
                    <X size={16} />
                  </button>
                </div>
              ))}
            </div>
          )}

          <button
            type="button"
            onClick={addCustomSymptom}
            className="mt-3 inline-flex items-center gap-1.5 text-[13px] text-accent hover:underline"
          >
            <Plus size={14} /> Agregar otro síntoma
          </button>
          <FieldError message={errors.emergencySymptoms} />
        </div>

        <div>
          <label className="block text-sm font-semibold text-navy mb-1">
            ¿Qué debe preguntar tu asistente antes de la cita?
          </label>
          <p className="text-xs text-slate-light mb-2.5">
            Lo que elijas aquí te llega en el aviso justo antes de la consulta, para que
            entres sabiendo a qué viene el paciente.
          </p>
          <div className="space-y-2">
            {intakeCatalog.map((question) => {
              const selected = data.intakeQuestions.includes(question.id)
              return (
                <button
                  key={question.id}
                  type="button"
                  onClick={() => toggleIntake(question.id)}
                  aria-pressed={selected}
                  className={`w-full flex items-center gap-3 p-3 rounded-lg border text-left transition-colors ${
                    selected ? 'border-primary-200 bg-primary-50' : 'border-line bg-white hover:border-slate-light'
                  }`}
                >
                  <Checkbox checked={selected} />
                  <span>
                    <span className={`block text-sm font-medium ${selected ? 'text-navy' : 'text-slate'}`}>
                      {question.label}
                    </span>
                    {question.description && (
                      <span className="block text-xs text-slate-light">{question.description}</span>
                    )}
                  </span>
                </button>
              )
            })}
          </div>
          <div className="mt-2">
            <Input
              label="Algo propio de tu especialidad (opcional)"
              placeholder="¿Usa lentes actualmente?"
              value={data.intakeCustom}
              onChange={(e) => onUpdate({ intakeCustom: e.target.value })}
            />
          </div>
          <FieldError message={errors.intakeQuestions} />
        </div>

        <div>
          <label className="block text-sm font-semibold text-navy mb-1">
            Notificaciones al doctor
          </label>
          <p className="text-xs text-slate-light mb-2.5">
            Elige de qué eventos quieres que el asistente te avise por WhatsApp. Puedes cambiarlo después.
          </p>
          <div className="space-y-2">
            {NOTIFICATION_DEFS.map((notif) => {
              const enabled = data[notif.key]
              return (
                <button
                  key={notif.key}
                  type="button"
                  onClick={() => onUpdate({ [notif.key]: !enabled } as Partial<PersonalizeData>)}
                  className={`w-full flex items-center gap-3 p-3 rounded-lg border text-left transition-colors ${
                    enabled ? 'border-primary-200 bg-primary-50' : 'border-line bg-white hover:border-slate-light'
                  }`}
                >
                  <Checkbox checked={enabled} />
                  <span>
                    <span className={`block text-sm font-medium ${enabled ? 'text-navy' : 'text-slate'}`}>
                      {notif.label}
                    </span>
                    <span className="block text-xs text-slate-light">{notif.description}</span>
                  </span>
                </button>
              )
            })}
          </div>
          <div className="flex items-start gap-2.5 p-3.5 mt-3 bg-off-white border border-line rounded-lg">
            <Lock size={15} className="text-accent flex-shrink-0 mt-0.5" strokeWidth={1.8} />
            <span className="text-[13px] text-slate leading-relaxed">
              El texto de estos avisos y el de los recordatorios está aprobado por WhatsApp y
              no se puede editar. Aquí decides cuáles se mandan, no qué dicen.
            </span>
          </div>
        </div>

        <div className="flex gap-3 pt-2">
          <Button variant="secondary" onClick={onBack}>
            Atrás
          </Button>
          <Button onClick={onNext} isLoading={loading} className="flex-1">
            Continuar
          </Button>
        </div>
      </CardBody>
    </Card>
  )
}
