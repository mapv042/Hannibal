import React from 'react'
import { Card, CardBody } from '@/components/ui/Card'
import { Button } from '@/components/ui/Button'
import { EyeMark } from '@/components/brand/EyeMark'
import { Calendar, MessageSquare, Bell, AlertTriangle } from 'lucide-react'

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
        <div className="flex justify-center mb-6">
          <EyeMark size={64} animate />
        </div>

        <h1 className="display text-[32px] mb-3">Bienvenido a ArgosAI</h1>
        <p className="text-[15px] text-slate mb-9 max-w-md mx-auto leading-relaxed">
          Configura tu asistente de WhatsApp en menos de 10 minutos. Te guiaremos paso a
          paso.
        </p>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 mb-9 text-left max-w-lg mx-auto">
          {features.map(({ icon: Icon, title, desc }) => (
            <div
              key={title}
              className="flex items-center gap-3.5 p-4 bg-off-white border border-line rounded-lg"
            >
              <Icon size={20} className="text-accent flex-shrink-0" strokeWidth={1.7} />
              <div>
                <p className="text-sm font-semibold text-navy">{title}</p>
                <p className="text-xs text-slate">{desc}</p>
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
