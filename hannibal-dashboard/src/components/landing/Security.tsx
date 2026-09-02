import React from 'react'
import { FadeUp } from '@/components/landing/FadeUp'

const CARDS = [
  {
    icon: (
      <>
        <rect x="4" y="10" width="16" height="10" rx="2" />
        <path d="M8 10V7a4 4 0 018 0v3" strokeLinecap="round" />
      </>
    ),
    title: 'Canal oficial, sin riesgo de bloqueo',
    body: 'Su número se integra vía la API oficial de WhatsApp Business — validado por Meta. Nada de automatización "no oficial" que ponga en riesgo su cuenta.',
  },
  {
    icon: <path d="M12 2l8 4v6c0 5-3.5 8.5-8 10-4.5-1.5-8-5-8-10V6l8-4z" />,
    title: 'Cifrado de extremo a extremo',
    body: 'Cada conversación viaja cifrada — la misma protección que WhatsApp usa para cualquier chat personal. Nadie más puede leerla en tránsito.',
  },
  {
    icon: (
      <>
        <circle cx="12" cy="12" r="9" />
        <path d="M12 7v5l3.5 2" />
      </>
    ),
    title: 'Retención limitada de datos',
    body: 'La información de sus pacientes se conserva solo el tiempo necesario para operar su agenda — no se comparte ni se usa fuera de su consultorio.',
  },
]

/**
 * The only section on a navy field. Trust is the argument that has to feel
 * different from the sales copy around it, so it gets its own ground.
 */
export function Security() {
  return (
    <section id="seguridad" className="px-6 py-20 text-center bg-navy scroll-mt-20">
      <div className="max-w-[1000px] mx-auto">
        <FadeUp>
          <div className="inline-flex items-center gap-2 bg-white/10 border border-white/[0.18] rounded-full px-4 py-1.5 mb-5 text-xs font-semibold text-white">
            <svg
              width="15"
              height="15"
              viewBox="0 0 24 24"
              fill="none"
              stroke="#fff"
              strokeWidth="2"
              aria-hidden="true"
            >
              <path d="M12 2l8 4v6c0 5-3.5 8.5-8 10-4.5-1.5-8-5-8-10V6l8-4z" />
            </svg>
            Infraestructura oficial de WhatsApp Business
          </div>

          <h2 className="font-serif font-semibold text-white text-[clamp(24px,3.5vw,34px)] leading-tight max-w-[620px] mx-auto mb-4">
            La seguridad de sus pacientes, tratada como se merece.
          </h2>

          <p className="text-[#A9B6CC] text-[15px] max-w-[560px] mx-auto mb-11 leading-relaxed">
            Argos no es un scraper ni una herramienta no oficial. Opera sobre la API
            oficial de WhatsApp Business — la misma infraestructura que usan miles de
            empresas verificadas por Meta en todo el mundo.
          </p>
        </FadeUp>

        <FadeUp delay={0.1}>
          <div className="grid md:grid-cols-3 gap-4 max-w-[940px] mx-auto mb-9 text-left">
            {CARDS.map((c) => (
              <div
                key={c.title}
                className="bg-white/5 border border-white/[0.12] rounded-2xl px-6 py-7"
              >
                <svg
                  width="24"
                  height="24"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="#fff"
                  strokeWidth="1.6"
                  className="mb-3.5"
                  aria-hidden="true"
                >
                  {c.icon}
                </svg>
                <h3 className="text-white text-[14.5px] font-semibold mb-2 leading-tight">
                  {c.title}
                </h3>
                <p className="text-[#A9B6CC] text-[12.5px] leading-normal">{c.body}</p>
              </div>
            ))}
          </div>

          <div className="flex items-start gap-2.5 text-left max-w-[620px] mx-auto px-5 py-4 bg-white/[0.04] border border-white/10 rounded-lg text-[13px] text-[#A9B6CC] leading-relaxed">
            <svg
              width="16"
              height="16"
              viewBox="0 0 24 24"
              fill="none"
              stroke="#8B96AD"
              strokeWidth="2"
              className="flex-shrink-0 mt-0.5"
              aria-hidden="true"
            >
              <circle cx="12" cy="12" r="10" />
              <path d="M9.5 9a2.5 2.5 0 015 0c0 1.5-2 1.5-2.5 3M12 17h.01" />
            </svg>
            <span>
              <strong className="text-white">¿Puede esto bloquear mi WhatsApp?</strong> No.
              Al usar el canal oficial y responder solo a conversaciones que el paciente
              inicia, su número queda igual o más protegido que usándolo manualmente.
            </span>
          </div>
        </FadeUp>
      </div>
    </section>
  )
}
