import React from 'react'
import Link from 'next/link'
import { Logo } from '@/components/ui/Logo'

export function LegalLayout({
  title,
  updated,
  children,
}: {
  title: string
  updated: string
  children: React.ReactNode
}) {
  return (
    <div className="bg-white min-h-screen">
      <nav className="flex items-center justify-between px-6 lg:px-10 py-4 border-b border-line">
        <Link href="/">
          <Logo size={28} />
        </Link>
        <div className="flex gap-6 text-[13.5px] text-slate">
          <Link href="/privacy" className="hover:text-navy transition-colors">
            Aviso de privacidad
          </Link>
          <Link href="/terms" className="hover:text-navy transition-colors">
            Términos de servicio
          </Link>
        </div>
      </nav>

      <main className="px-6 py-16">
        <div className="max-w-[720px] mx-auto">
          <h1 className="display text-[clamp(28px,4vw,38px)] mb-2">
            {title}
          </h1>
          <p className="text-sm text-slate-light mb-12">Última actualización: {updated}</p>
          <div className="prose-legal">{children}</div>
        </div>
      </main>

      <footer className="px-6 py-8 border-t border-line text-center text-[13px] text-slate">
        © 2026 Argos · Hecho en Guadalajara
      </footer>
    </div>
  )
}
