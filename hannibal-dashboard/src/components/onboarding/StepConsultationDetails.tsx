import React from 'react'
import { Card, CardBody, CardHeader } from '@/components/ui/Card'
import { Button } from '@/components/ui/Button'
import { Input } from '@/components/ui/Input'

export interface ConsultationData {
  newPatientCost: string
  returningPatientCost: string
  acceptsInsurance: string
  insuranceDetails: string
}

interface StepConsultationDetailsProps {
  data: ConsultationData
  onUpdate: (data: Partial<ConsultationData>) => void
  onNext: () => void
  onBack: () => void
}

export const StepConsultationDetails: React.FC<StepConsultationDetailsProps> = ({
  data,
  onUpdate,
  onNext,
  onBack,
}) => {
  return (
    <Card>
      <CardHeader>
        <h2 className="text-xl font-bold text-gray-900">Tu consulta</h2>
        <p className="text-sm text-gray-600 mt-1">
          Detalles que el asistente necesita para informar a los pacientes
        </p>
      </CardHeader>
      <CardBody className="space-y-5">
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <Input
            label="Costo primera consulta"
            placeholder="$800 MXN"
            value={data.newPatientCost}
            onChange={(e) => onUpdate({ newPatientCost: e.target.value })}
          />
          <Input
            label="Costo consulta subsecuente"
            placeholder="$600 MXN"
            value={data.returningPatientCost}
            onChange={(e) => onUpdate({ returningPatientCost: e.target.value })}
          />
        </div>
        <p className="text-xs text-gray-500 -mt-3">
          El asistente informara estos precios si el paciente pregunta
        </p>

        <div>
          <label className="block text-sm font-medium text-gray-700 mb-2">
            Aceptas seguros medicos?
          </label>
          <div className="flex gap-3">
            {['Si', 'No', 'Algunos'].map((option) => (
              <button
                key={option}
                type="button"
                onClick={() => onUpdate({ acceptsInsurance: option })}
                className={`px-5 py-2 rounded-lg border-2 text-sm font-medium transition-colors ${
                  data.acceptsInsurance === option
                    ? 'border-primary-500 bg-primary-50 text-primary-700'
                    : 'border-gray-200 bg-white text-gray-600 hover:border-gray-300'
                }`}
              >
                {option}
              </button>
            ))}
          </div>
        </div>

        {(data.acceptsInsurance === 'Si' || data.acceptsInsurance === 'Algunos') && (
          <Input
            label="Cuales seguros aceptas?"
            placeholder="GNP, AXA, Mapfre..."
            value={data.insuranceDetails}
            onChange={(e) => onUpdate({ insuranceDetails: e.target.value })}
          />
        )}

        <div className="flex gap-3 pt-2">
          <Button variant="secondary" onClick={onBack}>
            Atras
          </Button>
          <Button onClick={onNext} className="flex-1">
            Continuar
          </Button>
        </div>
      </CardBody>
    </Card>
  )
}
