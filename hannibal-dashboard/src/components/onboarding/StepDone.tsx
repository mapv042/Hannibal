import React from 'react'
import { Card, CardBody } from '@/components/ui/Card'
import { Button } from '@/components/ui/Button'
import { CheckCircle } from 'lucide-react'

interface StepDoneProps {
  officeName: string
  onFinish: () => void
  loading?: boolean
}

export const StepDone: React.FC<StepDoneProps> = ({
  officeName,
  onFinish,
  loading,
}) => {
  return (
    <Card>
      <CardBody className="text-center py-12 px-8">
        <div className="w-16 h-16 bg-green-100 rounded-full flex items-center justify-center mx-auto mb-6">
          <CheckCircle className="w-8 h-8 text-green-600" />
        </div>

        <h2 className="text-2xl font-bold text-gray-900 mb-2">
          Tu asistente esta listo!
        </h2>
        <p className="text-gray-600 mb-8">
          {officeName} ya esta configurado y listo para atender pacientes
        </p>

        <div className="bg-gray-50 rounded-lg p-5 mb-8 text-left max-w-md mx-auto">
          <p className="text-xs text-gray-500 uppercase tracking-wide mb-3">
            Que puedes hacer ahora
          </p>
          <ul className="space-y-2 text-sm text-gray-700">
            <li>- Ver tu agenda del dia en el panel</li>
            <li>- Conectar WhatsApp cuando estes listo</li>
            <li>- Ajustar horarios desde Configuracion</li>
          </ul>
        </div>

        <Button
          onClick={onFinish}
          isLoading={loading}
          className="w-full max-w-sm"
        >
          Ir al panel
        </Button>
      </CardBody>
    </Card>
  )
}
