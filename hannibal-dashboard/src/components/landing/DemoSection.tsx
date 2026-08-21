'use client'

import React, { useState } from 'react'
import Link from 'next/link'
import { WhatsAppPhone } from '@/components/landing/WhatsAppPhone'
import { FadeUp } from '@/components/landing/FadeUp'

/**
 * The demo, framed honestly.
 *
 * The reference design claimed "esto es real — escríbale ahora mismo" and "no
 * es una simulación". That copy belongs to a live model behind
 * `/api/demo/chat`; until that endpoint exists the replies come from a script,
 * and saying otherwise on a public page aimed at doctors is a claim we can't
 * back. The demo still shows the assistant's real behaviour — the wording just
 * says so accurately. Restore the live claim in the same commit that wires up
 * the endpoint (see the TODO in demoScript.ts).
 */
export function DemoSection() {
  const [engaged, setEngaged] = useState(false)

  return (
    <section id="demo" className="px-6 py-24 bg-off-white scroll-mt-20">
      <div className="max-w-[1080px] mx-auto grid lg:grid-cols-[1.05fr_0.95fr] gap-10 lg:gap-14 items-center">
        <FadeUp className="flex flex-col items-center min-w-0">
          {/* max-w-full + a shrinkable text span: a flex item defaults to
              min-width:auto, so without these the label refuses to wrap and
              pushes the page into horizontal scroll on narrow phones. */}
          <div className="inline-flex max-w-full items-center gap-2 border border-line bg-white rounded-full px-3.5 py-1.5 mb-4 text-xs font-semibold text-slate">
            <span className="w-1.5 h-1.5 rounded-full bg-accent flex-shrink-0" />
            <span className="min-w-0">Conversación de ejemplo — toque una sugerencia</span>
          </div>

          <WhatsAppPhone onEngaged={() => setEngaged(true)} />

          <Link
            href="/login"
            aria-hidden={!engaged}
            tabIndex={engaged ? 0 : -1}
            className="flex items-center justify-center gap-2 w-full max-w-[360px] bg-accent text-white
                       px-4 py-3 rounded-full text-[12.5px] font-bold text-center overflow-hidden
                       hover:bg-accent-bright transition-all duration-500"
            style={{
              opacity: engaged ? 1 : 0,
              maxHeight: engaged ? 60 : 0,
              marginTop: engaged ? 16 : 0,
              pointerEvents: engaged ? 'auto' : 'none',
            }}
          >
            <span className="min-w-0">¿Le gustó cómo respondió? Actívelo en su consultorio</span>
            <svg
              width="14"
              height="14"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2.5"
              className="flex-shrink-0"
              aria-hidden="true"
            >
              <path d="M5 12h14M13 6l6 6-6 6" />
            </svg>
          </Link>
        </FadeUp>

        <FadeUp delay={0.1} className="min-w-0">
          <div className="eyebrow mb-3">Véalo trabajar</div>
          <h2 className="display text-[clamp(24px,3.5vw,32px)] mb-4">
            Así contesta Sofía.
          </h2>
          <p className="text-slate text-[15px] mb-6 leading-relaxed">
            Pídale una cita, cancélela, pregúntele el costo — o descríbale una molestia
            seria y verá que no agenda: lo escala al doctor. Es el mismo criterio con el
            que atendería su consultorio.
          </p>

          <div
            className="flex items-start gap-3 border rounded-lg px-4 py-3.5 mb-4"
            style={{
              background: 'rgba(30,138,95,0.06)',
              borderColor: 'rgba(30,138,95,0.2)',
            }}
          >
            <svg
              width="18"
              height="18"
              viewBox="0 0 24 24"
              fill="none"
              stroke="#1E8A5F"
              strokeWidth="2"
              className="flex-shrink-0 mt-0.5"
              aria-hidden="true"
            >
              <circle cx="12" cy="12" r="10" />
              <path d="M12 6v6l4 2" />
            </svg>
            <div className="flex flex-col gap-0.5">
              <span className="font-serif text-base font-semibold text-brand-green">
                Menos de 3 segundos
              </span>
              <span className="text-[12.5px] text-slate leading-snug">
                es lo que tarda en contestarle a un paciente — de día, de noche o un
                domingo
              </span>
            </div>
          </div>

          <div className="border-l-[3px] border-line pl-4">
            <p className="font-serif italic text-base text-navy leading-normal mb-2">
              Las respuestas de arriba son las que da el asistente de verdad. Lo único
              que cambia en su consultorio son sus horarios, sus costos y su nombre.
            </p>
            <span className="text-xs text-slate">
              Configurarlo toma menos de 10 minutos.
            </span>
          </div>
        </FadeUp>
      </div>
    </section>
  )
}
