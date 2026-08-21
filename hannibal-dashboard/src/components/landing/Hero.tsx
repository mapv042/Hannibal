import React from 'react'
import Link from 'next/link'
import { EyeMark } from '@/components/brand/EyeMark'
import { FadeUp } from '@/components/landing/FadeUp'

/**
 * The four promises, stated as a specimen strip rather than four cards — they
 * belong to one claim, so they share one frame with hairline dividers.
 */
const VALUES: { icon: React.ReactNode; title: string; body: string }[] = [
  {
    icon: (
      <>
        <circle cx="12" cy="12" r="9" />
        <path d="M12 7v5l3.5 2" strokeLinecap="round" strokeLinejoin="round" />
      </>
    ),
    title: 'Nunca duerme',
    body: 'Activo 24 horas, los 7 días de la semana',
  },
  {
    icon: (
      <>
        <path
          d="M4 5h16a1 1 0 011 1v10a1 1 0 01-1 1H9l-5 4v-4H4a1 1 0 01-1-1V6a1 1 0 011-1z"
          strokeLinejoin="round"
        />
        <circle cx="8" cy="11" r="0.9" fill="currentColor" stroke="none" />
        <circle cx="12" cy="11" r="0.9" fill="currentColor" stroke="none" />
        <circle cx="16" cy="11" r="0.9" fill="currentColor" stroke="none" />
      </>
    ),
    title: 'Solo WhatsApp',
    body: 'Sin instalar apps, sin curva de aprendizaje — todo directo',
  },
  {
    icon: (
      <>
        <rect x="3" y="4" width="18" height="16" rx="2" />
        <path d="M7 9l3 3-3 3" strokeLinecap="round" strokeLinejoin="round" />
        <path d="M13 15h4" strokeLinecap="round" />
      </>
    ),
    title: 'Se controla con órdenes',
    body: '«Bloquéame la agenda», «confirma al de las 10am» — así de simple',
  },
  {
    icon: (
      <>
        <path
          d="M12 3v2M12 3a6 6 0 016 6c0 3.5 1 5 2 6H4c1-1 2-2.5 2-6a6 6 0 016-6z"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
        <path d="M9.5 19a2.5 2.5 0 005 0" strokeLinecap="round" />
        <circle cx="18" cy="6" r="3" fill="currentColor" stroke="none" />
      </>
    ),
    title: 'Sabe cuándo llamarlo',
    body: 'Detecta urgencias reales y lo alerta de inmediato',
  },
]

export function Hero() {
  return (
    <section
      className="relative min-h-[92vh] flex items-center justify-center px-6 pt-32 pb-16"
      style={{
        background:
          'radial-gradient(ellipse 800px 500px at 50% 15%, rgba(41,82,163,0.06), transparent), #fff',
      }}
    >
      <div className="max-w-[760px] text-center">
        <div className="flex justify-center mb-6">
          <EyeMark size={70} animate />
        </div>

        <h1 className="display text-[clamp(34px,5.5vw,58px)]">
          Su asistente de consultorio,
          <br />
          <em className="display-em">por WhatsApp.</em>
        </h1>

        <p className="mt-5 mx-auto max-w-[480px] text-[17px] text-slate">
          Agenda, reagenda, confirma citas y escala urgencias 24/7. Sin apps. Sin
          dashboards. Solo escríbale.
        </p>

        <div className="flex flex-wrap gap-3.5 justify-center mt-8 mb-11">
          <Link
            href="/login"
            className="bg-accent text-white px-7 py-[15px] rounded-sm text-[15px] font-bold hover:bg-accent-bright transition-colors"
          >
            Activar mi consultorio
          </Link>
          <a
            href="#demo"
            className="border border-line text-navy px-7 py-[15px] rounded-sm text-[15px] font-semibold hover:border-accent hover:bg-off-white transition-colors"
          >
            Ver una conversación
          </a>
        </div>

        <FadeUp>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-px bg-line max-w-[960px] mx-auto rounded-lg overflow-hidden border border-line">
            {VALUES.map((v) => (
              <div
                key={v.title}
                className="bg-off-white px-4 py-5 flex flex-col items-center text-center"
              >
                <svg
                  width="26"
                  height="26"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="1.6"
                  className="text-accent mb-2.5"
                  aria-hidden="true"
                >
                  {v.icon}
                </svg>
                <span className="text-[13.5px] font-bold text-navy leading-tight mb-1.5">
                  {v.title}
                </span>
                <span className="text-[11.5px] text-slate leading-snug">{v.body}</span>
              </div>
            ))}
          </div>
        </FadeUp>
      </div>
    </section>
  )
}
