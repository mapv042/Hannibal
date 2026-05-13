import React from 'react'
import { Card, CardBody } from '@/components/ui/Card'
import { Button } from '@/components/ui/Button'
import { Calendar, MessageSquare, Bell, Clock } from 'lucide-react'

interface StepWelcomeProps {
  onNext: () => void
}

const features = [
  { icon: Calendar, text: 'Agenda citas automaticamente' },
  { icon: MessageSquare, text: 'Atiende WhatsApp 24/7' },
  { icon: Bell, text: 'Detecta urgencias y te avisa' },
  { icon: Clock, text: 'Manda recordatorios automaticos' },
]

export const StepWelcome: React.FC<StepWelcomeProps> = ({ onNext }) => {
  return (
    <Card>
      <CardBody className="text-center py-12 px-8">
        <div className="w-16 h-16 bg-primary-100 rounded-full flex items-center justify-center mx-auto mb-6">
          <MessageSquare className="w-8 h-8 text-primary-600" />
        </div>

        <h1 className="text-2xl font-bold text-gray-900 mb-2">
          Bienvenido a Hannibal
        </h1>
        <p className="text-gray-600 mb-8">
          Configura tu asistente de WhatsApp en menos de 10 minutos
        </p>

        <div className="space-y-3 mb-8 text-left max-w-sm mx-auto">
          {features.map(({ icon: Icon, text }) => (
            <div key={text} className="flex items-center gap-3 p-3 bg-gray-50 rounded-lg">
              <Icon size={20} className="text-primary-600 flex-shrink-0" />
              <span className="text-sm text-gray-700">{text}</span>
            </div>
          ))}
        </div>

        <p className="text-sm text-gray-500 mb-6">
          Tiempo estimado: 8-10 minutos
        </p>

        <Button onClick={onNext} className="w-full max-w-sm">
          Comenzar
        </Button>
      </CardBody>
    </Card>
  )
}
