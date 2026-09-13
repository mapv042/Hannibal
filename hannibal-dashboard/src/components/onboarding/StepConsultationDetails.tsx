import React from 'react'
import { Card, CardBody } from '@/components/ui/Card'
import { Button } from '@/components/ui/Button'
import { FieldError } from '@/components/ui/FieldError'
import { StepHeader } from '@/components/onboarding/StepHeader'
import { Plus, X } from 'lucide-react'
import type {
  CatalogOption,
  InsuranceChoice,
  OfficeService,
} from '@/lib/constants/catalogs'
import type { FieldErrors } from '@/lib/validation/onboarding'

export interface ConsultationData {
  /** The doctor's catalogue. The first two rows are the generic consultations. */
  services: OfficeService[]
  acceptsInsurance: InsuranceChoice
  /** Canonical insurer ids, not free text. */
  insurances: string[]
}

interface StepConsultationDetailsProps {
  data: ConsultationData
  onUpdate: (data: Partial<ConsultationData>) => void
  onNext: () => void
  onBack: () => void
  errors?: FieldErrors
  /** Suggested services for the chosen specialty. */
  suggestedServices?: string[]
  insurers?: CatalogOption[]
}

const INSURANCE_OPTIONS: { value: InsuranceChoice; label: string; desc: string }[] = [
  { value: 'si', label: 'Sí', desc: 'Cualquier seguro' },
  { value: 'algunos', label: 'Algunos', desc: 'Solo los que indique' },
  { value: 'no', label: 'No', desc: 'Solo pago directo' },
]

export const StepConsultationDetails: React.FC<StepConsultationDetailsProps> = ({
  data,
  onUpdate,
  onNext,
  onBack,
  errors = {},
  suggestedServices = [],
  insurers = [],
}) => {
  const selectedNames = new Set(data.services.map((s) => s.name))

  const toggleService = (name: string) => {
    if (selectedNames.has(name)) {
      onUpdate({ services: data.services.filter((s) => s.name !== name) })
    } else {
      onUpdate({ services: [...data.services, { name, price: '' }] })
    }
  }

  const setPrice = (name: string, price: string) => {
    onUpdate({
      services: data.services.map((s) => (s.name === name ? { ...s, price } : s)),
    })
  }

  const addCustomService = () => {
    onUpdate({ services: [...data.services, { name: '', price: '' }] })
  }

  const updateCustomService = (index: number, patch: Partial<OfficeService>) => {
    onUpdate({
      services: data.services.map((s, i) => (i === index ? { ...s, ...patch } : s)),
    })
  }

  const removeService = (index: number) => {
    onUpdate({ services: data.services.filter((_, i) => i !== index) })
  }

  const toggleInsurer = (id: string) => {
    onUpdate({
      insurances: data.insurances.includes(id)
        ? data.insurances.filter((i) => i !== id)
        : [...data.insurances, id],
    })
  }

  // Rows the doctor typed in themselves ("Otro"), which aren't in the catalogue.
  const customRows = data.services
    .map((service, index) => ({ service, index }))
    .filter(({ service }) => !suggestedServices.includes(service.name))

  return (
    <Card>
      <CardBody className="space-y-6 p-8">
        <StepHeader
          eyebrow="Paso 3"
          title="Costos y seguros"
          subtitle="Para que el asistente pueda contestar preguntas sobre precios y formas de pago."
        />

        <div>
          <label className="block text-sm font-semibold text-slate mb-1">
            ¿Qué servicios ofreces?
          </label>
          <p className="text-[13px] text-slate-light mb-3">
            Elige los que des en tu consultorio y ponles precio. Puedes agregar los que falten.
          </p>

          <div className="space-y-2">
            {suggestedServices.map((name) => {
              const selected = selectedNames.has(name)
              const service = data.services.find((s) => s.name === name)
              return (
                <div
                  key={name}
                  className={`border rounded-lg p-3 transition-colors ${
                    selected ? 'border-accent bg-off-white' : 'border-line'
                  }`}
                >
                  <div className="flex items-center gap-3">
                    <button
                      type="button"
                      onClick={() => toggleService(name)}
                      className="flex items-center gap-2.5 flex-1 text-left"
                      aria-pressed={selected}
                    >
                      <span
                        className={`w-4 h-4 rounded border flex-shrink-0 ${
                          selected ? 'bg-accent border-accent' : 'border-line'
                        }`}
                      />
                      <span className="text-[15px] text-navy">{name}</span>
                    </button>
                    {selected && (
                      <input
                        type="text"
                        inputMode="numeric"
                        placeholder="$800"
                        value={service?.price ?? ''}
                        onChange={(e) => setPrice(name, e.target.value)}
                        className="input-field w-28 text-right"
                        aria-label={`Precio de ${name}`}
                      />
                    )}
                  </div>
                </div>
              )
            })}
          </div>

          {customRows.length > 0 && (
            <div className="space-y-2 mt-2">
              {customRows.map(({ service, index }) => (
                <div key={index} className="flex items-center gap-2">
                  <input
                    type="text"
                    placeholder="Nombre del servicio"
                    value={service.name}
                    onChange={(e) => updateCustomService(index, { name: e.target.value })}
                    className="input-field flex-1"
                    aria-label="Nombre del servicio"
                  />
                  <input
                    type="text"
                    inputMode="numeric"
                    placeholder="$800"
                    value={service.price}
                    onChange={(e) => updateCustomService(index, { price: e.target.value })}
                    className="input-field w-28 text-right"
                    aria-label="Precio del servicio"
                  />
                  <button
                    type="button"
                    onClick={() => removeService(index)}
                    className="text-slate-light hover:text-error p-1"
                    aria-label="Quitar servicio"
                  >
                    <X size={16} />
                  </button>
                </div>
              ))}
            </div>
          )}

          <button
            type="button"
            onClick={addCustomService}
            className="mt-3 inline-flex items-center gap-1.5 text-[13px] text-accent hover:underline"
          >
            <Plus size={14} /> Agregar otro servicio
          </button>
          <FieldError message={errors.services} />
        </div>

        <div>
          <label className="block text-sm font-semibold text-slate mb-2.5">
            ¿Aceptas seguros médicos?
          </label>
          <div className="grid grid-cols-3 gap-2.5">
            {INSURANCE_OPTIONS.map((option) => {
              const active = data.acceptsInsurance === option.value
              return (
                <button
                  key={option.value}
                  type="button"
                  onClick={() => onUpdate({ acceptsInsurance: option.value })}
                  className={`choice-card ${active ? 'selected' : ''}`}
                  data-field="acceptsInsurance"
                >
                  <p className="text-[15px] font-semibold text-navy">{option.label}</p>
                  <p className="text-xs text-slate-light mt-0.5">{option.desc}</p>
                </button>
              )
            })}
          </div>
          <FieldError message={errors.acceptsInsurance} />
        </div>

        {(data.acceptsInsurance === 'si' || data.acceptsInsurance === 'algunos') && (
          <div>
            <label className="block text-sm font-semibold text-slate mb-1">
              ¿Cuáles aceptas?
            </label>
            <p className="text-[13px] text-slate-light mb-3">
              Marca las que trabajas. Usamos el nombre oficial de cada una para que tu
              asistente siempre las mencione igual.
            </p>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
              {insurers.map((insurer) => {
                const selected = data.insurances.includes(insurer.id)
                return (
                  <button
                    key={insurer.id}
                    type="button"
                    onClick={() => toggleInsurer(insurer.id)}
                    aria-pressed={selected}
                    className={`flex items-center gap-2.5 border rounded-lg p-2.5 text-left transition-colors ${
                      selected ? 'border-accent bg-off-white' : 'border-line'
                    }`}
                  >
                    <span
                      className={`w-4 h-4 rounded border flex-shrink-0 ${
                        selected ? 'bg-accent border-accent' : 'border-line'
                      }`}
                    />
                    <span className="text-[14px] text-navy">{insurer.label}</span>
                  </button>
                )
              })}
            </div>
            <FieldError message={errors.insurances} />
          </div>
        )}

        <div className="flex gap-3 pt-2">
          <Button variant="secondary" onClick={onBack}>
            Atrás
          </Button>
          <Button onClick={onNext} className="flex-1">
            Continuar
          </Button>
        </div>
      </CardBody>
    </Card>
  )
}
