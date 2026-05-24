import React from 'react'
import { Card, CardBody } from '@/components/ui/Card'
import { Button } from '@/components/ui/Button'
import { MessageSquare, Check } from 'lucide-react'

interface StepConnectWhatsAppProps {
  onNext: () => void
  onBack: () => void
}

const benefits = [
  'Tus pacientes escriben al mismo numero de siempre',
  'Tu sigues viendo todos los chats en tu WhatsApp',
  'El bot solo responde cuando tu no estas respondiendo',
]

export const StepConnectWhatsApp: React.FC<StepConnectWhatsAppProps> = ({
  onNext,
  onBack,
}) => {
  return (
    <Card>
      <CardBody className="text-center py-12 px-8">
        <div
          className="w-20 h-20 rounded-3xl flex items-center justify-center mx-auto mb-7"
          style={{
            background: 'linear-gradient(135deg, #25d366, #128c7e)',
            boxShadow: '0 16px 40px rgba(37,211,102,.32), inset 0 1px 0 rgba(255,255,255,.3)',
          }}
        >
          <MessageSquare className="w-10 h-10 text-white" />
        </div>

        <h2 className="text-[26px] font-bold tracking-tight text-gray-900 mb-3">
          Conecta tu WhatsApp
        </h2>
        <p className="text-[15px] text-gray-600 mb-8 max-w-md mx-auto leading-relaxed">
          Hannibal usara el numero de tu consultorio. No necesitas otro celular ni cambiar de SIM.
        </p>

        <div className="border border-gray-200 rounded-2xl p-6 mb-8 text-left max-w-md mx-auto shadow-xs">
          <div className="space-y-0">
            {benefits.map((item, i) => (
              <div
                key={item}
                className={`flex items-start gap-3 py-2.5 ${
                  i < benefits.length - 1 ? 'border-b border-dashed border-gray-200' : ''
                }`}
              >
                <span className="w-5 h-5 rounded-full bg-green-100 text-green-700 flex items-center justify-center flex-shrink-0 mt-0.5">
                  <Check size={13} strokeWidth={2.6} />
                </span>
                <span className="text-sm text-gray-700 leading-relaxed">{item}</span>
              </div>
            ))}
          </div>

          <Button variant="secondary" className="w-full mt-5" disabled>
            Conectar WhatsApp (proximamente)
          </Button>
        </div>

        <div className="flex gap-3 max-w-md mx-auto">
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
