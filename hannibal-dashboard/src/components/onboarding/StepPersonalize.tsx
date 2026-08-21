import React from 'react'
import { Card, CardBody } from '@/components/ui/Card'
import { Button } from '@/components/ui/Button'
import { Input } from '@/components/ui/Input'
import { StepHeader } from '@/components/onboarding/StepHeader'

export interface PersonalizeData {
  assistantName: string
  assistantTone: 'formal' | 'informal'
  emergencySymptoms: string
  welcomeMessage: string
  notifyNewAppointment: boolean
  notifyCancellation: boolean
  notifyNewPatient: boolean
  notifyUnconfirmed: boolean
}

type NotifKey =
  | 'notifyNewAppointment'
  | 'notifyCancellation'
  | 'notifyNewPatient'
  | 'notifyUnconfirmed'

const NOTIFICATION_DEFS: { key: NotifKey; label: string; description: string }[] = [
  { key: 'notifyNewAppointment', label: 'Cita nueva agendada', description: 'Cuando el asistente agenda una cita.' },
  { key: 'notifyCancellation', label: 'Cancelación de paciente', description: 'Cuando un paciente cancela su cita.' },
  { key: 'notifyNewPatient', label: 'Paciente nuevo', description: 'Cuando se registra un paciente nuevo.' },
  { key: 'notifyUnconfirmed', label: 'Citas sin confirmar', description: 'Resumen al inicio del día con las citas de hoy sin confirmar.' },
]

interface StepPersonalizeProps {
  data: PersonalizeData
  onUpdate: (data: Partial<PersonalizeData>) => void
  onNext: () => void
  onBack: () => void
  loading?: boolean
}

export const StepPersonalize: React.FC<StepPersonalizeProps> = ({
  data,
  onUpdate,
  onNext,
  onBack,
  loading,
}) => {
  return (
    <Card>
      <CardBody className="space-y-5 p-8">
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
          helpText="Este nombre aparecerá en los mensajes a pacientes"
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
        </div>

        <div>
          <label className="block text-sm font-medium text-slate mb-1.5">
            Síntomas de emergencia
          </label>
          <textarea
            placeholder="Dolor severo, pérdida de visión, dificultad para respirar…"
            value={data.emergencySymptoms}
            onChange={(e) => onUpdate({ emergencySymptoms: e.target.value })}
            rows={3}
            className="input-field resize-none"
          />
          <p className="text-xs text-slate-light mt-1">
            El asistente te avisará cuando detecte estos síntomas
          </p>
        </div>

        <div>
          <label className="block text-sm font-medium text-slate mb-1.5">
            Mensaje de bienvenida
          </label>
          <textarea
            placeholder="Hola, soy Sofía del Consultorio del Dr. García. ¿En qué puedo ayudarte?"
            value={data.welcomeMessage}
            onChange={(e) => onUpdate({ welcomeMessage: e.target.value })}
            rows={3}
            className="input-field resize-none"
          />
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
                  <span
                    className={`w-5 h-5 rounded-sm flex items-center justify-center border transition-colors flex-shrink-0 ${
                      enabled ? 'bg-accent border-accent text-white' : 'bg-white border-slate-light'
                    }`}
                  >
                    {enabled && (
                      <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={3} d="M5 13l4 4L19 7" />
                      </svg>
                    )}
                  </span>
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
        </div>

        <div className="flex gap-3 pt-2">
          <Button variant="secondary" onClick={onBack}>
            Atrás
          </Button>
          <Button
            onClick={onNext}
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
