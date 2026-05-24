import React from 'react'
import { Card, CardBody } from '@/components/ui/Card'
import { Button } from '@/components/ui/Button'
import { Calendar, MessageSquare, Bell, AlertTriangle, Sparkles } from 'lucide-react'

interface StepWelcomeProps {
  onNext: () => void
}

const features = [
  { icon: MessageSquare, title: 'Atiende WhatsApp 24/7', desc: 'Como cualquier paciente' },
  { icon: Calendar, title: 'Agenda inteligente', desc: 'Detecta horarios libres' },
  { icon: Bell, title: 'Recordatorios', desc: 'Reduce ausencias' },
  { icon: AlertTriangle, title: 'Detecta urgencias', desc: 'Te avisa al instante' },
]

export const StepWelcome: React.FC<StepWelcomeProps> = ({ onNext }) => {
  return (
    <Card>
      <CardBody className="text-center py-12 px-8">
        <div
          className="w-20 h-20 rounded-3xl flex items-center justify-center mx-auto mb-7"
          style={{
            background: 'linear-gradient(135deg, #1535a3, #092b82)',
            boxShadow: '0 16px 40px rgba(var(--primary-rgb-500), .38), inset 0 1px 0 rgba(255,255,255,.3)',
          }}
        >
          <Sparkles className="w-9 h-9 text-white" strokeWidth={2.2} />
        </div>

        <h1 className="text-[32px] font-bold tracking-tight leading-tight text-gray-900 mb-3">
          Bienvenido a Hannibal
        </h1>
        <p className="text-base text-gray-600 mb-9 max-w-md mx-auto leading-relaxed">
          Configura tu asistente de WhatsApp en menos de 10 minutos.
          Te guiaremos paso a paso.
        </p>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 mb-9 text-left max-w-lg mx-auto">
          {features.map(({ icon: Icon, title, desc }) => (
            <div
              key={title}
              className="flex items-center gap-3.5 p-4 bg-white border border-gray-200 rounded-2xl shadow-xs"
            >
              <div className="w-10 h-10 rounded-[10px] bg-primary-50 flex items-center justify-center flex-shrink-0">
                <Icon size={20} className="text-primary-700" />
              </div>
              <div>
                <p className="text-sm font-semibold text-gray-900">{title}</p>
                <p className="text-xs text-gray-500">{desc}</p>
              </div>
            </div>
          ))}
        </div>

        <Button onClick={onNext} size="lg" className="w-full max-w-sm">
          Comenzar
        </Button>
      </CardBody>
    </Card>
  )
}
