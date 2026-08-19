import React from 'react'
import Link from 'next/link'
import { FadeUp } from '@/components/landing/FadeUp'

const INCLUDED = [
  'Agendamiento ilimitado — solo WhatsApp, incluye mensajes de voz',
  'Canal doctor incluido',
  'Instalación 100% hecha por nosotros',
  '2 semanas sin costo para probarlo',
]

export function Pricing() {
  return (
    <section id="precio" className="px-6 py-24 text-center bg-white scroll-mt-20">
      <FadeUp>
        {/* The one card allowed to float. Price is the decision, so it's the
            only surface on the page that lifts off the paper. */}
        <div className="max-w-[440px] mx-auto bg-white border border-line rounded-3xl px-10 py-11 shadow-lg">
          <div className="font-serif text-[46px] font-semibold text-navy leading-none">
            $3,499
            <span className="text-lg font-normal text-slate"> MXN / mes</span>
          </div>

          <div className="text-[12.5px] text-slate mt-2">
            + IVA (16%) — total: $4,058.84 MXN/mes
          </div>

          <div className="inline-flex items-center gap-1.5 text-[12.5px] text-accent mt-2.5 mb-6">
            <svg
              width="13"
              height="13"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              className="flex-shrink-0"
              aria-hidden="true"
            >
              <circle cx="12" cy="12" r="10" />
              <path d="M9 12l2 2 4-4" />
            </svg>
            Deducible de impuestos<span className="text-slate">*</span>
          </div>

          <div className="text-left">
            {INCLUDED.map((line, i) => (
              <div
                key={line}
                className={`text-sm text-slate py-2 ${i > 0 ? 'border-t border-line' : ''}`}
              >
                {line}
              </div>
            ))}
          </div>

          <Link
            href="/login"
            className="block w-full bg-accent text-white text-[15px] font-bold px-6 py-[15px] rounded-sm mt-6 hover:bg-accent-bright transition-colors"
          >
            Activar mi consultorio
          </Link>

          <p className="text-[11px] text-slate opacity-80 mt-5 leading-normal text-left">
            <span className="text-accent">*</span> Aplica para consultorios que facturan
            bajo un régimen fiscal que permite deducir gastos operativos. Consulte con su
            contador.
          </p>
        </div>
      </FadeUp>
    </section>
  )
}
