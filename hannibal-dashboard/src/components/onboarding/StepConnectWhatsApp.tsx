import React from 'react'
import { Card, CardBody } from '@/components/ui/Card'
import { Button } from '@/components/ui/Button'
import { MessageSquare } from 'lucide-react'

interface StepConnectWhatsAppProps {
  onNext: () => void
  onBack: () => void
}

export const StepConnectWhatsApp: React.FC<StepConnectWhatsAppProps> = ({
  onNext,
  onBack,
}) => {
  return (
    <Card>
      <CardBody className="text-center py-12 px-8">
        <div className="w-16 h-16 bg-green-100 rounded-full flex items-center justify-center mx-auto mb-6">
          <MessageSquare className="w-8 h-8 text-green-600" />
        </div>

        <h2 className="text-xl font-bold text-gray-900 mb-2">
          Conecta tu WhatsApp
        </h2>
        <p className="text-gray-600 mb-8 max-w-md mx-auto">
          Conecta tu numero de WhatsApp Business para que el asistente pueda responder a tus pacientes automaticamente
        </p>

        <div className="bg-gray-50 rounded-lg p-5 mb-8 text-left max-w-sm mx-auto space-y-3">
          {[
            'Responde mensajes 24/7',
            'Agenda citas sin tu intervencion',
            'Tu sigues usando WhatsApp normalmente',
          ].map((item) => (
            <div key={item} className="flex items-center gap-2">
              <span className="text-green-500 text-sm font-bold">&#10003;</span>
              <span className="text-sm text-gray-700">{item}</span>
            </div>
          ))}
        </div>

        <Button
          variant="secondary"
          className="w-full max-w-sm mb-3"
          disabled
        >
          Conectar WhatsApp (proximamente)
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
