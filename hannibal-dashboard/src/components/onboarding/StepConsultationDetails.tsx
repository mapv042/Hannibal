import React from 'react'
import { Card, CardBody } from '@/components/ui/Card'
import { Button } from '@/components/ui/Button'
import { Input } from '@/components/ui/Input'
import { StepHeader } from '@/components/onboarding/StepHeader'

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
      <CardBody className="space-y-5 p-8">
        <StepHeader
          eyebrow="Paso 3"
          title="Costos y seguros"
          subtitle="Para que el asistente pueda contestar preguntas sobre precios y formas de pago."
        />
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
          <label className="block text-sm font-semibold text-gray-700 mb-2.5">
            Aceptas seguros medicos?
          </label>
          <div className="grid grid-cols-3 gap-2.5">
            {[
              { value: 'Si', label: 'Si', desc: 'Cualquier seguro' },
              { value: 'Algunos', label: 'Algunos', desc: 'Solo los que indique' },
              { value: 'No', label: 'No', desc: 'Solo pago directo' },
            ].map((option) => {
              const active = data.acceptsInsurance === option.value
              return (
                <button
                  key={option.value}
                  type="button"
                  onClick={() => onUpdate({ acceptsInsurance: option.value })}
                  className={`text-left p-4 rounded-xl border transition-all ${
                    active
                      ? 'border-primary-500 bg-primary-50 ring-4 ring-primary-500/10'
                      : 'border-gray-200 bg-white shadow-xs hover:border-gray-300'
                  }`}
                >
                  <p className="text-[15px] font-semibold text-gray-900">{option.label}</p>
                  <p className="text-xs text-gray-500 mt-0.5">{option.desc}</p>
                </button>
              )
            })}
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
