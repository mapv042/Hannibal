import React from 'react'
import Link from 'next/link'
import { Logo } from '@/components/ui/Logo'

export function LandingNav() {
  return (
    <nav className="fixed top-0 inset-x-0 z-50 flex items-center justify-between px-5 sm:px-6 lg:px-10 py-4 border-b border-line bg-white/85 backdrop-blur-md">
      <Link href="/" aria-label="Argos — inicio">
        {/* The wordmark is the first thing to go when space is tight; the
            feather still identifies the site on its own. */}
        <span className="hidden min-[360px]:block">
          <Logo size={26} />
        </span>
        <span className="min-[360px]:hidden">
          <Logo size={26} withText={false} />
        </span>
      </Link>

      <div className="flex items-center gap-4 sm:gap-6">
        <div className="hidden md:flex gap-7 text-[13.5px] text-slate">
          <a href="#demo" className="hover:text-navy transition-colors">
            Demo
          </a>
          <a href="#pasos" className="hover:text-navy transition-colors">
            Cómo empieza
          </a>
          <a href="#precio" className="hover:text-navy transition-colors">
            Precio
          </a>
          <a href="#seguridad" className="hover:text-navy transition-colors">
            Seguridad
          </a>
        </div>

        {/*
          Always visible, including on phones. An existing customer opening the
          site on their phone needs a way in, and hiding this behind a
          breakpoint left them with nothing but the signup button.
        */}
        <Link
          href="/login"
          className="text-[13.5px] text-slate hover:text-navy transition-colors whitespace-nowrap"
        >
          Iniciar sesión
        </Link>
        <Link
          href="/login"
          className="bg-accent text-white px-4 sm:px-5 py-2.5 rounded-sm text-[13px] sm:text-sm font-bold hover:bg-accent-bright transition-colors whitespace-nowrap"
        >
          Empezar
          <span className="hidden sm:inline"> ahora</span>
        </Link>
      </div>
    </nav>
  )
}
