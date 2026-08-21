'use client'

import React, { useState } from 'react'
import Link from 'next/link'
import { createBrowserSupabaseClient } from '@/lib/supabase'
import { Card, CardBody } from '@/components/ui/Card'
import { Logo } from '@/components/ui/Logo'
import { GoogleGlyph } from '@/components/brand/GoogleGlyph'
import { Lock, ShieldCheck } from 'lucide-react'

export default function LoginPage() {
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const supabase = createBrowserSupabaseClient()

  const handleGoogleLogin = async () => {
    setError('')
    setLoading(true)
    try {
      const { error: oauthError } = await supabase.auth.signInWithOAuth({
        provider: 'google',
        options: {
          redirectTo: `${window.location.origin}/auth/callback`,
        },
      })
      if (oauthError) {
        setError(oauthError.message)
        setLoading(false)
      }
    } catch {
      setError('Error al iniciar sesión con Google. Intenta de nuevo.')
      setLoading(false)
    }
  }

  return (
    <div>
      {/* Logo */}
      <div className="flex justify-center mb-7">
        <Logo size={36} />
      </div>

      {/* Login Card */}
      <Card>
        <CardBody className="space-y-6 p-9">
          <div className="text-center">
            <h1 className="display text-[26px]">
              Bienvenido de vuelta
            </h1>
            <p className="text-slate text-sm mt-2.5 leading-relaxed">
              Inicia sesión para configurar tu asistente
              <br />y ver tu agenda.
            </p>
          </div>

          {error && (
            <div className="p-3 bg-red-50 border border-red-200 rounded-lg">
              <p className="text-sm text-red-800">{error}</p>
            </div>
          )}

          <button
            type="button"
            onClick={handleGoogleLogin}
            disabled={loading}
            className="w-full h-12 flex items-center justify-center gap-3 border border-line rounded-md bg-white hover:border-accent hover:bg-off-white transition-colors disabled:opacity-45 disabled:cursor-not-allowed"
          >
            <GoogleGlyph className="w-[18px] h-[18px]" />
            <span className="text-sm font-semibold text-navy">
              {loading ? 'Redirigiendo…' : 'Continuar con Google'}
            </span>
          </button>

          <p className="text-xs text-center text-slate-light">
            Al continuar, aceptas nuestros{' '}
            <Link href="/terms" className="underline hover:text-accent">
              términos de servicio
            </Link>{' '}
            y{' '}
            <Link href="/privacy" className="underline hover:text-accent">
              aviso de privacidad
            </Link>
          </p>
        </CardBody>
      </Card>

      {/* Trust microcopy */}
      <div className="mt-5 flex items-center justify-center gap-4 text-xs text-slate">
        <span className="inline-flex items-center gap-1.5">
          <Lock size={13} /> SSL cifrado
        </span>
        <span className="w-[3px] h-[3px] rounded-full bg-slate-light" />
        <span className="inline-flex items-center gap-1.5">
          <ShieldCheck size={13} /> Datos en México
        </span>
      </div>
    </div>
  )
}
