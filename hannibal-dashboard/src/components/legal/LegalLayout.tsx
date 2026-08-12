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
      <nav className="flex items-center justify-between px-6 lg:px-14 py-5 border-b border-gray-200">
        <Link href="/">
          <Logo size={28} />
        </Link>
        <div className="flex gap-6 text-sm font-medium text-gray-600">
          <Link href="/privacy" className="hover:text-gray-900 transition-colors">
            Aviso de privacidad
          </Link>
          <Link href="/terms" className="hover:text-gray-900 transition-colors">
            Términos de servicio
          </Link>
        </div>
      </nav>

      <main className="px-6 py-16">
        <div className="max-w-[720px] mx-auto">
          <h1 className="text-3xl lg:text-4xl font-bold tracking-tight text-gray-900 mb-2">
            {title}
          </h1>
          <p className="text-sm text-gray-500 mb-12">Última actualización: {updated}</p>
          <div className="prose-legal">{children}</div>
        </div>
      </main>

      <footer className="px-6 py-8 border-t border-gray-200 text-center text-[13px] text-gray-500">
        © 2026 ArgosAI · Hecho en CDMX
      </footer>
    </div>
  )
}
