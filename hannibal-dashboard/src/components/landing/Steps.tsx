import React from 'react'
import { FadeUp } from '@/components/landing/FadeUp'

const STEPS = [
  {
    n: '1',
    title: 'Llene el formulario',
    body: 'Sus horarios, su especialidad, cómo quiere que hable ArgosAI. 10 minutos.',
  },
  {
    n: '2',
    title: 'Conecte su calendario',
    body: 'Un clic para autorizar Google Calendar. Así de simple.',
  },
  {
    n: '3',
    title: 'Preparamos su número',
    body: 'Usted sigue contestando su WhatsApp normal. No se entera del proceso — nosotros nos encargamos.',
  },
  {
    n: '4',
    title: 'Usted elige la hora del cambio',
    body: 'Le avisamos cuándo está listo. ArgosAI entra exactamente cuando usted diga — cero interrupciones.',
    highlight: true,
  },
]

export function Steps() {
  return (
    <section id="pasos" className="px-6 py-20 bg-off-white scroll-mt-20">
      <FadeUp className="max-w-[1000px] mx-auto text-center">
        <div className="eyebrow mb-3">Así empieza</div>
        <h2 className="display text-[clamp(24px,3.5vw,32px)] mb-10">
          Cuatro pasos. Nosotros hacemos tres.
        </h2>

        <div className="flex flex-col md:flex-row items-stretch justify-center gap-3.5">
          {STEPS.map((s, i) => (
            <React.Fragment key={s.n}>
              <div
                className={`flex-1 min-w-0 border rounded-lg px-4 py-6 text-left ${
                  s.highlight ? 'border-accent bg-white' : 'border-line bg-white'
                }`}
                style={
                  s.highlight
                    ? {
                        background:
                          'linear-gradient(160deg, #fff, rgba(41,82,163,0.04))',
                      }
                    : undefined
                }
              >
                <div
                  className={`w-7 h-7 rounded-full font-mono text-[13px] font-medium flex items-center justify-center mb-3.5 ${
                    s.highlight ? 'bg-accent text-white' : 'bg-primary-50 text-accent'
                  }`}
                >
                  {s.n}
                </div>
                <h3 className="text-[14.5px] font-semibold text-navy mb-1.5">{s.title}</h3>
                <p className="text-[12.5px] text-slate leading-normal">{s.body}</p>
              </div>

              {i < STEPS.length - 1 && (
                <div
                  className="flex items-center justify-center text-accent opacity-35 text-base rotate-90 md:rotate-0 -my-1 md:my-0"
                  aria-hidden="true"
                >
                  →
                </div>
              )}
            </React.Fragment>
          ))}
        </div>

        {/* The objection every doctor raises: "¿y mientras tanto qué pasa con
            mi WhatsApp?" It gets answered right where it comes up. */}
        <div
          className="flex items-center gap-2.5 justify-center max-w-[620px] mx-auto mt-8 px-5 py-3.5 border text-[13px] text-slate text-left rounded-xl md:rounded-full"
          style={{
            background: 'rgba(30,138,95,0.06)',
            borderColor: 'rgba(30,138,95,0.2)',
          }}
        >
          <svg width="18" height="18" viewBox="0 0 18 18" fill="none" className="flex-shrink-0" aria-hidden="true">
            <path
              d="M9 1.5l7 3.2v4.1c0 4.2-2.9 7.4-7 8.7-4.1-1.3-7-4.5-7-8.7V4.7L9 1.5z"
              stroke="#1E8A5F"
              strokeWidth="1.3"
            />
            <path
              d="M6 9l2 2 4-4.3"
              stroke="#1E8A5F"
              strokeWidth="1.4"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
          <span>
            Su WhatsApp nunca se detiene. Del paso 1 al 3 usted opera como siempre — el
            único momento del cambio es el que usted mismo elige en el paso 4.
          </span>
        </div>
      </FadeUp>
    </section>
  )
}
