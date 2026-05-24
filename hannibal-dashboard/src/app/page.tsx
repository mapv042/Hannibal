import React from 'react'
import Link from 'next/link'
import { Logo } from '@/components/ui/Logo'
import { Badge } from '@/components/ui/Badge'
import { WhatsAppPhone } from '@/components/landing/WhatsAppPhone'
import {
  ArrowRight,
  Play,
  CalendarDays,
  MessageCircle,
  AlertTriangle,
  Bell,
  Settings,
  Sparkles,
  Check,
} from 'lucide-react'

export const dynamic = 'force-dynamic'

// ─── Nav ──────────────────────────────────────────────────────────────
function LandingNav() {
  return (
    <nav className="sticky top-0 z-10 flex items-center justify-between px-6 lg:px-14 py-5 border-b border-gray-200 bg-white/85 backdrop-blur-md">
      <Logo size={28} />
      <div className="hidden md:flex gap-8 text-sm font-medium text-gray-600">
        <a href="#beneficios" className="hover:text-gray-900 transition-colors">Producto</a>
        <a href="#beneficios" className="hover:text-gray-900 transition-colors">Beneficios</a>
        <a href="#como-funciona" className="hover:text-gray-900 transition-colors">Cómo funciona</a>
        <a href="#precio" className="hover:text-gray-900 transition-colors">Precio</a>
      </div>
      <div className="flex gap-2.5 items-center">
        <Link href="/login" className="text-sm font-medium text-gray-700 px-3 hover:text-gray-900 transition-colors">
          Iniciar sesión
        </Link>
        <Link href="/login" className="button-primary">
          Comenzar gratis
        </Link>
      </div>
    </nav>
  )
}

// ─── Hero ─────────────────────────────────────────────────────────────
function Stat({ n, label }: { n: string; label: string }) {
  return (
    <div>
      <div className="text-[26px] font-bold tracking-tight text-gray-900 leading-none">{n}</div>
      <div className="text-[13px] text-gray-500 mt-1">{label}</div>
    </div>
  )
}

function FloatChip({
  icon: Icon,
  title,
  subtitle,
  tone,
  className = '',
}: {
  icon: React.ElementType
  title: string
  subtitle: string
  tone: 'primary' | 'success'
  className?: string
}) {
  const tones = {
    primary: 'bg-primary-50 text-primary-700',
    success: 'bg-green-100 text-green-700',
  }[tone]
  return (
    <div
      className={`flex items-center gap-2.5 bg-white rounded-2xl border border-gray-200 py-2.5 pl-2.5 pr-3.5 shadow-[0_12px_30px_rgba(15,30,40,.10),0_2px_6px_rgba(15,30,40,.06)] ${className}`}
    >
      <div className={`w-9 h-9 rounded-[10px] flex items-center justify-center ${tones}`}>
        <Icon size={18} />
      </div>
      <div>
        <div className="text-[13px] font-semibold text-gray-900">{title}</div>
        <div className="text-xs text-gray-500">{subtitle}</div>
      </div>
    </div>
  )
}

function LandingHero() {
  return (
    <section
      className="relative px-6 lg:px-14 pt-20 pb-20 overflow-hidden"
      style={{
        background: `radial-gradient(ellipse 80% 60% at 80% 20%, rgba(var(--primary-rgb-500), .12), transparent 60%),
                     radial-gradient(ellipse 60% 50% at 10% 100%, rgba(var(--secondary-rgb-500), .08), transparent 60%),
                     #fff`,
      }}
    >
      <div
        className="absolute inset-0 pointer-events-none opacity-40"
        style={{
          backgroundImage:
            'linear-gradient(#e5e7eb 1px, transparent 1px), linear-gradient(90deg, #e5e7eb 1px, transparent 1px)',
          backgroundSize: '64px 64px',
          maskImage: 'radial-gradient(ellipse 90% 70% at 30% 30%, #000, transparent 70%)',
          WebkitMaskImage: 'radial-gradient(ellipse 90% 70% at 30% 30%, #000, transparent 70%)',
        }}
      />
      <div className="relative grid lg:grid-cols-[1.05fr_0.95fr] gap-14 items-center max-w-[1240px] mx-auto">
        {/* Copy */}
        <div>
          <Badge variant="primary" dot className="mb-5">
            Asistente de IA · 24/7 en WhatsApp
          </Badge>
          <h1 className="text-5xl lg:text-[64px] font-bold tracking-tight text-gray-900 leading-[1.04]">
            Tu asistente de<br />
            WhatsApp que<br />
            <span
              className="bg-clip-text text-transparent"
              style={{ backgroundImage: 'linear-gradient(120deg, #092b82, #1535a3)' }}
            >
              nunca descansa.
            </span>
          </h1>
          <p className="mt-5 mb-9 text-lg lg:text-[19px] leading-relaxed text-gray-600 max-w-[520px]">
            Hannibal agenda citas, manda recordatorios, atiende cancelaciones y filtra urgencias por ti
            — directamente desde el WhatsApp de tu consultorio. Sin contratar a nadie.
          </p>
          <div className="flex flex-wrap gap-3 items-center">
            <Link
              href="/login"
              className="inline-flex items-center justify-center gap-2.5 h-14 px-7 rounded-xl bg-primary-600 text-white text-base font-semibold tracking-tight shadow-[0_8px_24px_rgba(var(--primary-rgb-600),.28)] hover:bg-primary-700 transition-colors"
            >
              Comenzar gratis
              <ArrowRight size={20} />
            </Link>
            <a
              href="#como-funciona"
              className="inline-flex items-center justify-center gap-2.5 h-14 px-7 rounded-xl text-gray-700 text-base font-semibold tracking-tight hover:bg-gray-100 transition-colors"
            >
              <Play size={20} />
              Ver demo (2 min)
            </a>
          </div>
          <div className="flex flex-wrap gap-7 mt-9 items-center">
            <Stat n="+340" label="doctores activos" />
            <div className="w-px h-8 bg-gray-200" />
            <Stat n="14k" label="citas agendadas / mes" />
            <div className="w-px h-8 bg-gray-200" />
            <Stat n="3.2 hrs" label="ahorradas al día" />
          </div>
        </div>

        {/* Phone */}
        <div className="relative flex justify-center items-start">
          <div
            className="absolute -inset-8"
            style={{
              background:
                'radial-gradient(ellipse 70% 70% at 50% 50%, rgba(var(--primary-rgb-500), .22), transparent 70%)',
              filter: 'blur(20px)',
            }}
          />
          <div className="relative" style={{ transform: 'rotate(-2deg)' }}>
            <WhatsAppPhone width={320} />
          </div>
          <FloatChip
            className="absolute top-14 -left-2"
            icon={CalendarDays}
            tone="primary"
            title="Cita confirmada"
            subtitle="Jue 25 sep · 17:30"
          />
          <FloatChip
            className="absolute bottom-20 -right-3"
            icon={Bell}
            tone="success"
            title="Recordatorio enviado"
            subtitle="A 12 pacientes · hoy 9:00"
          />
        </div>
      </div>

      {/* Trusted by */}
      <div className="relative mt-20 pt-8 border-t border-gray-200 max-w-[1240px] mx-auto flex items-center justify-between flex-wrap gap-4">
        <span className="text-[13px] text-gray-500 uppercase tracking-wide font-semibold">
          Confían en Hannibal
        </span>
        <div className="flex flex-wrap gap-x-10 gap-y-2 items-center opacity-70">
          {['Clínica Polanco', 'Dr. R. Méndez', 'Dental Roma', 'Salud Mente', 'Pediátrica Norte', 'Dra. Castillo'].map(
            (n) => (
              <span key={n} className="text-[15px] font-bold text-gray-500 tracking-tight">
                {n}
              </span>
            )
          )}
        </div>
      </div>
    </section>
  )
}

// ─── Section eyebrow ───────────────────────────────────────────────────
function SectionEyebrow({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex items-center gap-2.5">
      <span className="w-6 h-0.5 bg-primary-500 rounded-full" />
      <span className="text-xs font-bold tracking-widest uppercase text-primary-700">{children}</span>
    </div>
  )
}

// ─── Benefits ──────────────────────────────────────────────────────────
function LandingBenefits() {
  const items = [
    {
      icon: CalendarDays,
      title: 'Agenda citas automáticamente',
      body: 'El asistente entiende mensajes en lenguaje natural, ofrece horarios disponibles y confirma la cita en tu calendario.',
    },
    {
      icon: MessageCircle,
      title: 'Atiende WhatsApp 24/7',
      body: 'Tus pacientes nunca quedan sin respuesta — ni a las 2 AM, ni en domingo, ni cuando estás en consulta.',
    },
    {
      icon: AlertTriangle,
      title: 'Detecta urgencias y te avisa',
      body: 'Si un paciente describe síntomas críticos, el bot escala el mensaje directo a tu WhatsApp personal.',
    },
    {
      icon: Bell,
      title: 'Manda recordatorios automáticos',
      body: '24h antes de cada cita el bot recuerda al paciente. Reduce las ausencias hasta en 60%.',
    },
  ]
  return (
    <section id="beneficios" className="px-6 lg:px-14 py-24 bg-gray-50">
      <div className="max-w-[1240px] mx-auto">
        <SectionEyebrow>Por qué Hannibal</SectionEyebrow>
        <h2 className="text-4xl lg:text-[44px] font-bold tracking-tight my-4 max-w-3xl leading-tight text-gray-900">
          Tu consultorio atendido las 24 horas, los 7 días de la semana.
        </h2>
        <p className="text-[17px] text-gray-600 max-w-2xl mb-14">
          Cuatro cosas que hace todos los días, mientras tú te dedicas a lo importante: atender a tus pacientes.
        </p>
        <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-5">
          {items.map(({ icon: Icon, title, body }) => (
            <div
              key={title}
              className="card p-7 flex flex-col gap-3.5 hover:shadow-md transition-shadow"
            >
              <div
                className="w-12 h-12 rounded-xl flex items-center justify-center text-primary-700"
                style={{ background: 'linear-gradient(135deg, #eef1fa, #d3dcf2)' }}
              >
                <Icon size={22} />
              </div>
              <div className="text-[17px] font-semibold tracking-tight text-gray-900">{title}</div>
              <div className="text-sm leading-relaxed text-gray-600">{body}</div>
            </div>
          ))}
        </div>
      </div>
    </section>
  )
}

// ─── How it works ────────────────────────────────────────────────────
function LandingHowItWorks() {
  const steps = [
    { n: '01', title: 'Configura tu consultorio', body: 'Horarios, costos, especialidad, mensajes. En menos de 10 minutos.', icon: Settings, time: '~10 min' },
    { n: '02', title: 'Conecta tu WhatsApp', body: 'Vincula el número del consultorio con un solo clic. Sin SIMs, sin equipos.', icon: MessageCircle, time: '~30 seg' },
    { n: '03', title: 'El asistente atiende pacientes', body: 'A partir de aquí, Sofía contesta cada mensaje, agenda y avisa. Tú revisas el dashboard.', icon: Sparkles, time: 'Para siempre' },
  ]
  return (
    <section id="como-funciona" className="px-6 lg:px-14 py-24 bg-white">
      <div className="max-w-[1240px] mx-auto">
        <SectionEyebrow>Cómo funciona</SectionEyebrow>
        <h2 className="text-4xl lg:text-[44px] font-bold tracking-tight mt-3 mb-14 leading-tight max-w-3xl text-gray-900">
          Tres pasos. Diez minutos. Listo para siempre.
        </h2>
        <div className="grid md:grid-cols-3 gap-6 relative">
          <div
            className="hidden md:block absolute top-[38px] left-[12%] right-[12%] h-0.5 z-0"
            style={{
              background:
                'repeating-linear-gradient(to right, #6c87d9 0 8px, transparent 8px 16px)',
            }}
          />
          {steps.map(({ n, title, body, icon: Icon, time }) => (
            <div key={n} className="relative z-[1]">
              <div className="w-[76px] h-[76px] rounded-[22px] bg-white border-2 border-primary-500 text-primary-700 flex items-center justify-center text-[22px] font-bold mb-6 shadow-[0_8px_24px_rgba(var(--primary-rgb-500),.22)]">
                {n}
              </div>
              <div className="flex items-center gap-2.5 mb-2.5">
                <Icon size={18} className="text-primary-600" />
                <Badge variant="default">{time}</Badge>
              </div>
              <div className="text-[22px] font-semibold tracking-tight mb-2 text-gray-900">{title}</div>
              <div className="text-[15px] leading-relaxed text-gray-600 max-w-xs">{body}</div>
            </div>
          ))}
        </div>
      </div>
    </section>
  )
}

// ─── Pricing ──────────────────────────────────────────────────────────
function LandingPricing() {
  const features = [
    'WhatsApp del consultorio conectado',
    'Citas ilimitadas',
    'Recordatorios automáticos',
    'Detección de urgencias',
    'Integración con Google Calendar',
    'Panel web para configurar todo',
    'Soporte por WhatsApp',
    '14 días gratis · cancelas cuando quieras',
  ]
  return (
    <section
      id="precio"
      className="px-6 lg:px-14 py-24"
      style={{ background: 'linear-gradient(180deg, #fff, #f9fafb 60%)' }}
    >
      <div className="max-w-[1240px] mx-auto text-center">
        <div className="flex justify-center">
          <SectionEyebrow>Precio</SectionEyebrow>
        </div>
        <h2 className="text-4xl lg:text-[44px] font-bold tracking-tight mt-3 mb-4 leading-tight text-gray-900">
          Un solo plan. Todo incluido.
        </h2>
        <p className="text-[17px] text-gray-600 max-w-xl mx-auto mb-12">
          Sin niveles, sin extras escondidos, sin contratos anuales. Pagas mes a mes.
        </p>
        <div
          className="card max-w-xl mx-auto overflow-hidden text-left border-primary-200"
          style={{ boxShadow: '0 24px 60px rgba(var(--primary-rgb-500), .22), 0 4px 12px rgba(15,30,40,.04)' }}
        >
          <div
            className="px-6 py-3.5 flex items-center justify-between text-white text-[13px] font-semibold uppercase tracking-wide"
            style={{ background: 'linear-gradient(135deg, #092b82, #061e5e)' }}
          >
            <span>Plan profesional</span>
            <span className="bg-white/20 rounded-full px-2.5 py-0.5 text-xs font-semibold normal-case">
              14 días gratis
            </span>
          </div>
          <div className="px-8 pt-10 pb-8">
            <div className="flex items-baseline gap-2">
              <span className="text-[64px] font-bold tracking-tight leading-none text-gray-900">$1,499</span>
              <span className="text-lg text-gray-500">MXN / mes</span>
            </div>
            <div className="text-sm text-gray-500 mt-2 mb-7">
              IVA incluido · Sin contrato · Cancela cuando quieras
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 mb-7">
              {features.map((f) => (
                <div key={f} className="flex items-start gap-2 text-sm text-gray-700">
                  <span className="w-[18px] h-[18px] rounded-full bg-primary-50 text-primary-700 flex items-center justify-center flex-shrink-0 mt-0.5">
                    <Check size={12} strokeWidth={2.6} />
                  </span>
                  <span>{f}</span>
                </div>
              ))}
            </div>
            <Link
              href="/login"
              className="w-full inline-flex items-center justify-center gap-2.5 h-12 rounded-xl bg-primary-600 text-white text-[15px] font-semibold tracking-tight shadow-[0_4px_12px_rgba(var(--primary-rgb-600),.22)] hover:bg-primary-700 transition-colors"
            >
              Comenzar mis 14 días gratis
              <ArrowRight size={18} />
            </Link>
            <div className="text-center text-[13px] text-gray-500 mt-3.5">
              No pedimos tarjeta para empezar.
            </div>
          </div>
        </div>
      </div>
    </section>
  )
}

// ─── Footer ──────────────────────────────────────────────────────────
function LandingFooter() {
  const cols = [
    { title: 'Producto', links: ['Características', 'Beneficios', 'Precio', 'Cambios'] },
    { title: 'Compañía', links: ['Sobre nosotros', 'Contacto', 'Blog', 'Términos'] },
    { title: 'Soporte', links: ['Centro de ayuda', 'Documentación', 'Estatus', 'WhatsApp'] },
  ]
  return (
    <footer className="bg-[#0f1419] text-[#a1a8b3] px-6 lg:px-14 pt-14 pb-8">
      <div className="max-w-[1240px] mx-auto grid md:grid-cols-[1.5fr_1fr_1fr_1fr] gap-10">
        <div>
          <div className="mb-4">
            <Logo size={28} light />
          </div>
          <p className="text-sm leading-relaxed max-w-xs text-[#a1a8b3]">
            Hannibal es el asistente de WhatsApp para profesionales de salud independientes en México.
            Hecho con cuidado en CDMX.
          </p>
        </div>
        {cols.map((col) => (
          <div key={col.title}>
            <div className="text-[13px] font-bold text-white uppercase tracking-wide mb-4">{col.title}</div>
            <div className="flex flex-col gap-2.5">
              {col.links.map((l) => (
                <a key={l} href="#" className="text-sm text-[#a1a8b3] hover:text-white transition-colors">
                  {l}
                </a>
              ))}
            </div>
          </div>
        ))}
      </div>
      <div className="max-w-[1240px] mx-auto mt-10 pt-6 border-t border-[#1f2730] text-[13px] text-gray-500 flex flex-col sm:flex-row justify-between items-center gap-2">
        <span>© 2026 Hannibal · Hecho en CDMX</span>
        <span>Aviso de privacidad · Términos de servicio</span>
      </div>
    </footer>
  )
}

export default function LandingPage() {
  return (
    <div className="bg-white min-h-screen">
      <LandingNav />
      <LandingHero />
      <LandingBenefits />
      <LandingHowItWorks />
      <LandingPricing />
      <LandingFooter />
    </div>
  )
}
