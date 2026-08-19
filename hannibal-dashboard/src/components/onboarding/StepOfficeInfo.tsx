import React from 'react'
import { Card, CardBody } from '@/components/ui/Card'
import { Button } from '@/components/ui/Button'
import { Input } from '@/components/ui/Input'
import { StepHeader } from '@/components/onboarding/StepHeader'
import { Lock } from 'lucide-react'
import { MEXICAN_STATES } from '@/lib/constants/mexican-states'

export interface OfficeInfoData {
  officeName: string
  specialty: string
  city: string
  state: string
  address: string
  ownerPhone: string
}

interface StepOfficeInfoProps {
  data: OfficeInfoData
  onUpdate: (data: Partial<OfficeInfoData>) => void
  onNext: () => void
  onBack: () => void
  loading?: boolean
}

export const StepOfficeInfo: React.FC<StepOfficeInfoProps> = ({
  data,
  onUpdate,
  onNext,
  onBack,
  loading,
}) => {
  const canContinue = data.officeName.trim().length > 0

  return (
    <Card>
      <CardBody className="space-y-5 p-8">
        <StepHeader
          eyebrow="Paso 1"
          title="Cuéntanos sobre tu consultorio"
          subtitle="Esta información ayuda al asistente a presentar tu práctica correctamente a los pacientes."
        />
        <Input
          label="Nombre del consultorio"
          placeholder="Consultorio Oftalmológico García"
          value={data.officeName}
          onChange={(e) => onUpdate({ officeName: e.target.value })}
          required
        />

        <Input
          label="Especialidad"
          placeholder="Oftalmología"
          value={data.specialty}
          onChange={(e) => onUpdate({ specialty: e.target.value })}
        />

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <Input
            label="Ciudad"
            placeholder="Guadalajara"
            value={data.city}
            onChange={(e) => onUpdate({ city: e.target.value })}
          />
          <div>
            <label className="block text-sm font-medium text-slate mb-1.5">
              Estado
            </label>
            <select
              value={data.state}
              onChange={(e) => onUpdate({ state: e.target.value })}
              className="input-field"
            >
              <option value="">Selecciona un estado</option>
              {MEXICAN_STATES.map((state) => (
                <option key={state} value={state}>
                  {state}
                </option>
              ))}
            </select>
          </div>
        </div>

        <Input
          label="Tu WhatsApp personal"
          placeholder="+52 33 1234 5678"
          value={data.ownerPhone}
          onChange={(e) => onUpdate({ ownerPhone: e.target.value })}
        />

        <Input
          label="Dirección del consultorio"
          placeholder="Av. México 1234, Col. Americana"
          value={data.address}
          onChange={(e) => onUpdate({ address: e.target.value })}
        />

        <div className="flex items-start gap-2.5 p-3.5 bg-off-white border border-line rounded-lg">
          <Lock size={15} className="text-accent flex-shrink-0 mt-0.5" strokeWidth={1.8} />
          <span className="text-[13px] text-slate leading-relaxed">
            Todos tus datos se almacenan cifrados en servidores en México. Nunca compartimos información con terceros.
          </span>
        </div>

        <div className="flex gap-3 pt-2">
          <Button variant="secondary" onClick={onBack}>
            Atrás
          </Button>
          <Button
            onClick={onNext}
            disabled={!canContinue}
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
