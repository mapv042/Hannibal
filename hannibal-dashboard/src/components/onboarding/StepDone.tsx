import React from 'react'
import { Card, CardBody } from '@/components/ui/Card'
import { Button } from '@/components/ui/Button'
import { Check, Calendar, MessageSquare, Settings } from 'lucide-react'

interface StepDoneProps {
  officeName: string
  onFinish: () => void
  loading?: boolean
}

const nextSteps = [
  { icon: Calendar, label: 'Ve tu agenda del día en el panel' },
  { icon: MessageSquare, label: 'Conecta WhatsApp cuando estés listo' },
  { icon: Settings, label: 'Ajusta horarios desde Configuración' },
]

export const StepDone: React.FC<StepDoneProps> = ({
  officeName,
  onFinish,
  loading,
}) => {
  return (
    <Card>
      <CardBody className="text-center py-12 px-8">
        {/* Green appears exactly once in the whole flow, and this is it: the
            only moment something has actually completed. */}
        <div
          className="w-16 h-16 rounded-full flex items-center justify-center mx-auto mb-6 border"
          style={{
            background: 'rgba(30,138,95,0.08)',
            borderColor: 'rgba(30,138,95,0.28)',
          }}
        >
          <Check className="w-8 h-8 text-brand-green" strokeWidth={2.4} />
        </div>

        <h2 className="display text-[32px] mb-3">¡Tu asistente está listo!</h2>
        <p className="text-[15px] text-slate mb-8 max-w-md mx-auto leading-relaxed">
          {officeName} ya está configurado y listo para atender pacientes.
        </p>

        <div className="max-w-md mx-auto text-left border border-line rounded-xl overflow-hidden mb-8">
          {nextSteps.map(({ icon: Icon, label }, i) => (
            <div
              key={label}
              className={`flex items-center gap-3.5 px-5 py-3.5 ${
                i < nextSteps.length - 1 ? 'border-b border-line' : ''
              }`}
            >
              <Icon size={18} className="text-accent flex-shrink-0" strokeWidth={1.7} />
              <span className="text-sm text-navy">{label}</span>
            </div>
          ))}
        </div>

        <Button onClick={onFinish} isLoading={loading} size="lg" className="w-full max-w-sm">
          Ir al panel
        </Button>
      </CardBody>
    </Card>
  )
}
