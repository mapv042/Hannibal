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
  { icon: Calendar, label: 'Ve tu agenda del dia en el panel' },
  { icon: MessageSquare, label: 'Conecta WhatsApp cuando estes listo' },
  { icon: Settings, label: 'Ajusta horarios desde Configuracion' },
]

export const StepDone: React.FC<StepDoneProps> = ({
  officeName,
  onFinish,
  loading,
}) => {
  return (
    <Card>
      <CardBody className="text-center py-12 px-8">
        <div
          className="w-24 h-24 rounded-full flex items-center justify-center mx-auto mb-7"
          style={{
            background: 'linear-gradient(135deg, #10b981, #059669)',
            boxShadow: '0 16px 40px rgba(16,185,129,.35), inset 0 1px 0 rgba(255,255,255,.3)',
          }}
        >
          <Check className="w-12 h-12 text-white" strokeWidth={3} />
        </div>

        <h2 className="text-[32px] font-bold tracking-tight leading-tight text-gray-900 mb-3">
          Tu asistente esta listo!
        </h2>
        <p className="text-base text-gray-600 mb-8 max-w-md mx-auto leading-relaxed">
          {officeName} ya esta configurado y listo para atender pacientes.
        </p>

        <Card className="max-w-md mx-auto text-left overflow-hidden mb-8">
          {nextSteps.map(({ icon: Icon, label }, i) => (
            <div
              key={label}
              className={`flex items-center gap-3.5 px-5 py-4 ${
                i < nextSteps.length - 1 ? 'border-b border-gray-200' : ''
              }`}
            >
              <div className="w-9 h-9 rounded-lg bg-gray-50 flex items-center justify-center flex-shrink-0">
                <Icon size={18} className="text-gray-700" />
              </div>
              <span className="text-sm font-medium text-gray-800">{label}</span>
            </div>
          ))}
        </Card>

        <Button onClick={onFinish} isLoading={loading} size="lg" className="w-full max-w-sm">
          Ir al panel
        </Button>
      </CardBody>
    </Card>
  )
}
