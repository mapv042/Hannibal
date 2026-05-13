import React from 'react'
import { Card, CardBody } from '@/components/ui/Card'
import { Button } from '@/components/ui/Button'
import { Calendar } from 'lucide-react'

interface StepConnectCalendarProps {
  onNext: () => void
  onBack: () => void
}

export const StepConnectCalendar: React.FC<StepConnectCalendarProps> = ({
  onNext,
  onBack,
}) => {
  return (
    <Card>
      <CardBody className="text-center py-12 px-8">
        <div className="w-16 h-16 bg-blue-100 rounded-full flex items-center justify-center mx-auto mb-6">
          <Calendar className="w-8 h-8 text-blue-600" />
        </div>

        <h2 className="text-xl font-bold text-gray-900 mb-2">
          Conecta tu calendario
        </h2>
        <p className="text-gray-600 mb-8 max-w-md mx-auto">
          Sincroniza tu Google Calendar para que el asistente vea tu disponibilidad en tiempo real
        </p>

        <div className="bg-gray-50 rounded-lg p-5 mb-8 text-left max-w-sm mx-auto space-y-3">
          {[
            'Ve tu disponibilidad en tiempo real',
            'Agenda citas sin conflictos de horario',
            'Nunca duplicara una cita',
            'Tus datos son solo tuyos',
          ].map((item) => (
            <div key={item} className="flex items-center gap-2">
              <span className="text-blue-500 text-sm font-bold">&#10003;</span>
              <span className="text-sm text-gray-700">{item}</span>
            </div>
          ))}
        </div>

        <Button
          variant="secondary"
          className="w-full max-w-sm mb-3"
          disabled
        >
          Conectar Google Calendar (proximamente)
        </Button>

        <div className="flex gap-3 max-w-sm mx-auto">
          <Button variant="secondary" onClick={onBack}>
            Atras
          </Button>
          <Button onClick={onNext} className="flex-1">
            Omitir por ahora
          </Button>
        </div>
      </CardBody>
    </Card>
  )
}
