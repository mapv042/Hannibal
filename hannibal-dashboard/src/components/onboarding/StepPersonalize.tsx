import React from 'react'
import { Card, CardBody, CardHeader } from '@/components/ui/Card'
import { Button } from '@/components/ui/Button'
import { Input } from '@/components/ui/Input'

export interface PersonalizeData {
  assistantName: string
  assistantTone: 'formal' | 'informal'
  emergencySymptoms: string
  welcomeMessage: string
}

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
      <CardHeader>
        <h2 className="text-xl font-bold text-gray-900">Personaliza tu asistente</h2>
        <p className="text-sm text-gray-600 mt-1">
          Asi se comunicara con tus pacientes
        </p>
      </CardHeader>
      <CardBody className="space-y-5">
        <Input
          label="Nombre del asistente"
          placeholder="Sofia"
          value={data.assistantName}
          onChange={(e) => onUpdate({ assistantName: e.target.value })}
          helpText="Este nombre aparecera en los mensajes a pacientes"
        />

        <div>
          <label className="block text-sm font-medium text-gray-700 mb-2">
            Tono de conversacion
          </label>
          <div className="grid grid-cols-2 gap-3">
            {[
              { value: 'formal' as const, label: 'De usted', desc: '"Buenos dias, en que le puedo ayudar"' },
              { value: 'informal' as const, label: 'De tu', desc: '"Hola, en que te puedo ayudar?"' },
            ].map((option) => (
              <button
                key={option.value}
                type="button"
                onClick={() => onUpdate({ assistantTone: option.value })}
                className={`p-4 rounded-lg border-2 text-left transition-colors ${
                  data.assistantTone === option.value
                    ? 'border-primary-500 bg-primary-50'
                    : 'border-gray-200 bg-white hover:border-gray-300'
                }`}
              >
                <p className={`text-sm font-medium ${
                  data.assistantTone === option.value ? 'text-primary-700' : 'text-gray-900'
                }`}>
                  {option.label}
                </p>
                <p className="text-xs text-gray-500 mt-1 italic">{option.desc}</p>
              </button>
            ))}
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
