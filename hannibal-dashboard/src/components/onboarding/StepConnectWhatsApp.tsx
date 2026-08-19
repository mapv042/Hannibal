import React from 'react'
import { Card, CardBody } from '@/components/ui/Card'
import { Button } from '@/components/ui/Button'
import { StepHeader } from '@/components/onboarding/StepHeader'
import { Check } from 'lucide-react'

interface StepConnectWhatsAppProps {
  onNext: () => void
  onBack: () => void
}

const benefits = [
  'Tus pacientes escriben al mismo número de siempre',
  'Tú sigues viendo todos los chats en tu WhatsApp',
  'El bot solo responde cuando tú no estás respondiendo',
]

export const StepConnectWhatsApp: React.FC<StepConnectWhatsAppProps> = ({
  onNext,
  onBack,
}) => {
  return (
    <Card>
      <CardBody className="p-8">
        <StepHeader
          eyebrow="Paso 5"
          title="Conecta tu WhatsApp"
          subtitle="ArgosAI usará el número de tu consultorio. No necesitas otro celular ni cambiar de SIM."
        />

        <div className="border border-line rounded-xl p-6 mb-6">
          <div className="space-y-0">
            {benefits.map((item, i) => (
              <div
                key={item}
                className={`flex items-start gap-3 py-2.5 ${
                  i < benefits.length - 1 ? 'border-b border-line' : ''
                }`}
              >
                <Check
                  size={16}
                  className="text-brand-green flex-shrink-0 mt-0.5"
                  strokeWidth={2.6}
                />
                <span className="text-sm text-slate leading-relaxed">{item}</span>
              </div>
            ))}
          </div>

          <Button variant="secondary" className="w-full mt-5" disabled>
            Conectar WhatsApp (próximamente)
          </Button>
        </div>

        <div className="flex gap-3">
          <Button variant="secondary" onClick={onBack}>
            Atrás
          </Button>
          <Button onClick={onNext} className="flex-1">
            Omitir por ahora
          </Button>
        </div>
      </CardBody>
    </Card>
  )
}
