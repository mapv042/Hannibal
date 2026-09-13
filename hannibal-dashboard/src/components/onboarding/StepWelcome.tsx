import React from 'react'
import { Card, CardBody } from '@/components/ui/Card'
import { Button } from '@/components/ui/Button'
import { EyeMark } from '@/components/brand/EyeMark'

interface StepWelcomeProps {
  onNext: () => void
}

/**
 * Deliberately not a feature list. The doctor already read the four benefits on
 * the landing page and clicked through — repeating them here reads as a pitch to
 * someone who already said yes. What they need now is to know what the next ten
 * minutes ask of them and what they get at the end.
 */
const steps = [
  { n: '1', title: 'Tu consultorio', desc: 'Dónde estás y cómo te localizan' },
  { n: '2', title: 'Tus horarios', desc: 'Cuándo puede agendarte' },
  { n: '3', title: 'Tus precios', desc: 'Qué contestar sobre costos y seguros' },
  { n: '4', title: 'Tu asistente', desc: 'Cómo se llama y cómo habla' },
]

export const StepWelcome: React.FC<StepWelcomeProps> = ({ onNext }) => {
  return (
    <Card>
      <CardBody className="text-center py-12 px-8">
        <div className="flex justify-center mb-6">
          <EyeMark size={64} animate />
        </div>

        <h1 className="display text-[32px] mb-3">Vamos a darle vida a tu asistente</h1>
        <p className="text-[15px] text-slate mb-9 max-w-md mx-auto leading-relaxed">
          Cuatro pasos y queda contestando tu WhatsApp. Solo necesitamos que nos cuentes
          cómo trabajas — nosotros nos encargamos del resto.
        </p>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 mb-6 text-left max-w-lg mx-auto">
          {steps.map(({ n, title, desc }) => (
            <div
              key={n}
              className="flex items-center gap-3.5 p-4 bg-off-white border border-line rounded-lg"
            >
              <span className="w-7 h-7 rounded-full bg-accent text-white text-[13px] font-semibold flex items-center justify-center flex-shrink-0">
                {n}
              </span>
              <div>
                <p className="text-sm font-semibold text-navy">{title}</p>
                <p className="text-xs text-slate">{desc}</p>
              </div>
            </div>
          ))}
        </div>

        <p className="text-[13px] text-slate-light mb-9">
          Toma menos de 10 minutos. Puedes cambiar todo después.
        </p>

        <Button onClick={onNext} size="lg" className="w-full max-w-sm">
          Empezar
        </Button>
      </CardBody>
    </Card>
  )
}
