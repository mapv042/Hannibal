import React from 'react'
import { FadeUp } from '@/components/landing/FadeUp'

const WE_TAKE = [
  'Nos aseguramos que sus pacientes asistan a la consulta',
  'Le llenamos el hueco cuando alguien cancela',
  'Le adelantamos citas si se libera un espacio antes',
  'Contestamos aunque sea medianoche o domingo',
  'Le avisamos de inmediato si hay algo que solo usted puede resolver',
]

const YOU_KEEP = [
  'El diagnóstico',
  'La conversación con el paciente',
  'Las decisiones que importan',
  'El tiempo con su familia',
]

/**
 * The division of labour, drawn as a division. The left column is struck
 * through with a dash and set in slate — work leaving the doctor's hands. The
 * right is a filled bullet in accent, heavier and darker — what stays.
 */
export function Statement() {
  return (
    <section className="px-6 py-24 bg-white">
      <FadeUp className="max-w-[760px] mx-auto text-center">
        <div className="eyebrow mb-4">Por qué existe Argos</div>

        <h2 className="display text-[clamp(26px,4.2vw,40px)] leading-[1.3]">
          Déjenos la parte repetitiva.
          <span className="block text-accent font-medium italic">
            Usted quédese con la parte humana.
          </span>
        </h2>

        <p className="text-slate text-[15.5px] max-w-[540px] mx-auto mt-5 mb-12 leading-relaxed">
          Confirmar horarios, recordar citas, contestar a las 11 de la noche — eso lo
          administramos nosotros. Usted concéntrese en el paciente que tiene enfrente.
        </p>

        <div className="grid md:grid-cols-[1fr_auto_1fr] gap-6 md:gap-7 items-start text-left max-w-[620px] mx-auto">
          <div>
            <div className="text-[11px] font-bold uppercase tracking-wide text-slate mb-3.5">
              Se lo llevamos nosotros
            </div>
            <ul className="flex flex-col gap-3.5">
              {WE_TAKE.map((item) => (
                <li
                  key={item}
                  className="relative pl-[22px] text-[13.5px] text-slate leading-normal
                             before:absolute before:left-0 before:top-2 before:w-3 before:h-px
                             before:bg-slate before:opacity-50"
                >
                  {item}
                </li>
              ))}
            </ul>
          </div>

          <div className="hidden md:block w-px bg-line self-stretch" />

          <div>
            <div className="text-[11px] font-bold uppercase tracking-wide text-accent mb-3.5">
              Se queda con usted
            </div>
            <ul className="flex flex-col gap-3.5">
              {YOU_KEEP.map((item) => (
                <li
                  key={item}
                  className="relative pl-[22px] text-[15px] font-semibold text-navy leading-snug
                             before:absolute before:left-0 before:top-[6px] before:w-2 before:h-2
                             before:rounded-full before:bg-accent"
                >
                  {item}
                </li>
              ))}
            </ul>
          </div>
        </div>
      </FadeUp>
    </section>
  )
}
