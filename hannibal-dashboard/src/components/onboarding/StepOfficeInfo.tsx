import React from 'react'
import { Card, CardBody } from '@/components/ui/Card'
import { Button } from '@/components/ui/Button'
import { Input } from '@/components/ui/Input'
import { FieldError } from '@/components/ui/FieldError'
import { StepHeader } from '@/components/onboarding/StepHeader'
import { Lock } from 'lucide-react'
import { MEXICAN_STATES } from '@/lib/constants/mexican-states'
import { OTHER_SPECIALTY_ID, type CatalogOption } from '@/lib/constants/catalogs'
import type { FieldErrors } from '@/lib/validation/onboarding'

export interface OfficeInfoData {
  doctorFirstName: string
  doctorLastName: string
  officeName: string
  /** Catalogue id, or OTHER_SPECIALTY_ID when the doctor picks "Otra". */
  specialty: string
  /** Free text, only used when specialty === OTHER_SPECIALTY_ID. */
  specialtyOther: string
  city: string
  state: string
  address: string
  ownerPhone: string
  secondaryOwnerPhone: string
}

interface StepOfficeInfoProps {
  data: OfficeInfoData
  onUpdate: (data: Partial<OfficeInfoData>) => void
  onNext: () => void
  onBack: () => void
  loading?: boolean
  errors?: FieldErrors
  specialties?: CatalogOption[]
}

export const StepOfficeInfo: React.FC<StepOfficeInfoProps> = ({
  data,
  onUpdate,
  onNext,
  onBack,
  loading,
  errors = {},
  specialties = [],
}) => {
  return (
    <Card>
      <CardBody className="space-y-5 p-8">
        <StepHeader
          eyebrow="Paso 1"
          title="Cuéntanos sobre tu consultorio"
          subtitle="Esta información ayuda al asistente a presentar tu práctica correctamente a los pacientes."
        />

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <Input
            label="Tu nombre"
            placeholder="Luis"
            value={data.doctorFirstName}
            onChange={(e) => onUpdate({ doctorFirstName: e.target.value })}
            error={errors.doctorFirstName}
            data-field="doctorFirstName"
          />
          <Input
            label="Tus apellidos"
            placeholder="García Ramírez"
            value={data.doctorLastName}
            onChange={(e) => onUpdate({ doctorLastName: e.target.value })}
            error={errors.doctorLastName}
            helpText="Así te saludamos en tu panel"
            data-field="doctorLastName"
          />
        </div>

        <Input
          label="Nombre del consultorio"
          placeholder="Consultorio Oftalmológico García"
          value={data.officeName}
          onChange={(e) => onUpdate({ officeName: e.target.value })}
          error={errors.officeName}
          data-field="officeName"
        />

        <div>
          <label className="block text-[13px] text-slate mb-1.5">Especialidad</label>
          <select
            value={data.specialty}
            onChange={(e) => onUpdate({ specialty: e.target.value })}
            className={`input-field ${errors.specialty ? 'border-error' : ''}`}
            data-field="specialty"
          >
            <option value="">Selecciona tu especialidad</option>
            {specialties.map((s) => (
              <option key={s.id} value={s.id}>
                {s.label}
              </option>
            ))}
          </select>
          <FieldError message={errors.specialty} />
          {!errors.specialty && (
            <p className="mt-1.5 text-[13px] text-slate-light">
              Con esto te sugerimos tus servicios y síntomas de alarma en los siguientes pasos.
            </p>
          )}
        </div>

        {data.specialty === OTHER_SPECIALTY_ID && (
          <Input
            label="¿Cuál es tu especialidad?"
            placeholder="Medicina del deporte"
            value={data.specialtyOther}
            onChange={(e) => onUpdate({ specialtyOther: e.target.value })}
            error={errors.specialtyOther}
            data-field="specialtyOther"
          />
        )}

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <Input
            label="Ciudad"
            placeholder="Guadalajara"
            value={data.city}
            onChange={(e) => onUpdate({ city: e.target.value })}
            error={errors.city}
            data-field="city"
          />
          <div>
            <label className="block text-[13px] text-slate mb-1.5">Estado</label>
            <select
              value={data.state}
              onChange={(e) => onUpdate({ state: e.target.value })}
              className={`input-field ${errors.state ? 'border-error' : ''}`}
              data-field="state"
            >
              <option value="">Selecciona un estado</option>
              {MEXICAN_STATES.map((state) => (
                <option key={state} value={state}>
                  {state}
                </option>
              ))}
            </select>
            <FieldError message={errors.state} />
          </div>
        </div>

        <Input
          label="Dirección del consultorio"
          placeholder="Av. México 1234, Col. Americana"
          value={data.address}
          onChange={(e) => onUpdate({ address: e.target.value })}
          error={errors.address}
          helpText="Tu asistente se la da a los pacientes cuando preguntan dónde estás."
          data-field="address"
        />

        <Input
          label="Tu WhatsApp personal"
          placeholder="+52 33 1234 5678"
          value={data.ownerPhone}
          onChange={(e) => onUpdate({ ownerPhone: e.target.value })}
          error={errors.ownerPhone}
          helpText="A este número te va a escribir tu asistente: aquí te avisa de citas nuevas y urgencias, y desde aquí le das instrucciones."
          data-field="ownerPhone"
        />

        <Input
          label="¿Alguien más debe recibir los avisos? (opcional)"
          placeholder="+52 33 8765 4321"
          value={data.secondaryOwnerPhone}
          onChange={(e) => onUpdate({ secondaryOwnerPhone: e.target.value })}
          error={errors.secondaryOwnerPhone}
          helpText="Por ejemplo tu secretaria. Recibe exactamente los mismos mensajes que tú y puede darle las mismas instrucciones al asistente."
          data-field="secondaryOwnerPhone"
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
          <Button onClick={onNext} isLoading={loading} className="flex-1">
            Continuar
          </Button>
        </div>
      </CardBody>
    </Card>
  )
}
