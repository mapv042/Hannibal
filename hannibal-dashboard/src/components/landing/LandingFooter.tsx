import React from 'react'
import Link from 'next/link'
import { Logo } from '@/components/ui/Logo'

export function LandingFooter() {
  return (
    <footer className="bg-navy-deep px-6 pt-11 pb-8 text-center border-t border-white/[0.06]">
      <div className="flex justify-center mb-3">
        <Logo size={22} light />
      </div>

      <p className="text-[#A9B6CC] text-xs">Guadalajara, México · argosai.mx</p>

      {/*
        These two links are not decoration: Google's OAuth verification checks
        that the homepage links to the privacy policy, and the branding review
        that just passed depends on it. Do not drop them.
      */}
      <div className="flex items-center justify-center gap-2 mt-4 text-xs text-[#A9B6CC]">
        <Link href="/privacy" className="hover:text-white transition-colors">
          Aviso de privacidad
        </Link>
        <span aria-hidden="true">·</span>
        <Link href="/terms" className="hover:text-white transition-colors">
          Términos de servicio
        </Link>
      </div>

      <p className="text-[11px] text-[#A9B6CC] opacity-60 mt-4">
        © 2026 Argos · Operado por Miguel Angel Partida Velasco
      </p>
    </footer>
  )
}
