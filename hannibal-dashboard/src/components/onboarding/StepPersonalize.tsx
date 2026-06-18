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
          subtitle="Decide como se llama, como habla y que considera una emergencia."
        />
        <Input
          label="Nombre del asistente"
          placeholder="Sofia"
          value={data.assistantName}
          onChange={(e) => onUpdate({ assistantName: e.target.value })}
          helpText="Este nombre aparecera en los mensajes a pacientes"
        />

        <div>
          <label className="block text-sm font-semibold text-gray-700 mb-2.5">
            Tono de conversacion
          </label>
          <div className="grid grid-cols-2 gap-2.5">
            {[
              { value: 'formal' as const, label: 'De usted', desc: 'Formal, profesional', example: '"Buen dia, en que le puedo ayudar?"' },
              { value: 'informal' as const, label: 'De tu', desc: 'Cercano, casual', example: '"Hola! En que te ayudo?"' },
            ].map((option) => {
              const active = data.assistantTone === option.value
              return (
                <button
                  key={option.value}
                  type="button"
                  onClick={() => onUpdate({ assistantTone: option.value })}
                  className={`p-4 rounded-xl border text-left transition-all ${
                    active
                      ? 'border-primary-500 bg-primary-50 ring-4 ring-primary-500/10'
                      : 'border-gray-200 bg-white shadow-xs hover:border-gray-300'
                  }`}
                >
                  <p className="text-[15px] font-semibold text-gray-900">{option.label}</p>
                  <p className="text-xs text-gray-500 mt-0.5 mb-2.5">{option.desc}</p>
                  <p className={`text-[12.5px] italic px-2.5 py-2 rounded-lg border border-gray-200 text-gray-700 ${
                    active ? 'bg-white' : 'bg-gray-50'
                  }`}>
                    {option.example}
                  </p>
                </button>
              )
            })}
          </div>
        </div>

        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1.5">
            Sintomas de emergencia
          </label>
          <textarea
            placeholder="Dolor severo, perdida de vision, dificultad para respirar..."
            value={data.emergencySymptoms}
            onChange={(e) => onUpdate({ emergencySymptoms: e.target.value })}
            rows={3}
            className="input-field resize-none"
          />
          <p className="text-xs text-gray-500 mt-1">
            El asistente te avisara cuando detecte estos sintomas
          </p>
        </div>

        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1.5">
            Mensaje de bienvenida
          </label>
          <textarea
            placeholder="Hola, soy Sofia del Consultorio del Dr. Garcia. En que puedo ayudarte?"
            value={data.welcomeMessage}
            onChange={(e) => onUpdate({ welcomeMessage: e.target.value })}
            rows={3}
            className="input-field resize-none"
          />
        </div>

        <div>
          <label className="block text-sm font-semibold text-gray-700 mb-1">
            Notificaciones al doctor
          </label>
          <p className="text-xs text-gray-500 mb-2.5">
            Elige de que eventos quieres que el asistente te avise por WhatsApp. Puedes cambiarlo despues.
          </p>
          <div className="space-y-2">
            {NOTIFICATION_DEFS.map((notif) => {
              const enabled = data[notif.key]
              return (
                <button
                  key={notif.key}
                  type="button"
                  onClick={() => onUpdate({ [notif.key]: !enabled } as Partial<PersonalizeData>)}
                  className={`w-full flex items-center gap-3 p-3 rounded-xl border text-left transition-colors ${
                    enabled ? 'border-primary-200 bg-primary-50' : 'border-gray-200 bg-gray-50'
                  }`}
                >
                  <span
                    className={`w-6 h-6 rounded flex items-center justify-center border-2 transition-colors flex-shrink-0 ${
                      enabled ? 'bg-primary-600 border-primary-600 text-white' : 'bg-white border-gray-300'
                    }`}
                  >
                    {enabled && (
                      <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={3} d="M5 13l4 4L19 7" />
                      </svg>
                    )}
                  </span>
                  <span>
                    <span className={`block text-sm font-medium ${enabled ? 'text-gray-900' : 'text-gray-500'}`}>
                      {notif.label}
                    </span>
                    <span className="block text-xs text-gray-500">{notif.description}</span>
                  </span>
                </button>
              )
            })}
          </div>
        </div>

        <div className="flex gap-3 pt-2">
          <Button variant="secondary" onClick={onBack}>
            Atras
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
