'use client'

import React, { useState } from 'react'
import { createBrowserSupabaseClient } from '@/lib/supabase'
import { Card, CardBody } from '@/components/ui/Card'
import { Logo } from '@/components/ui/Logo'
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
      <Card
        className="shadow-lg"
        style={{ borderColor: 'rgba(229,231,235,.7)' }}
      >
        <CardBody className="space-y-6 p-9">
          <div className="text-center">
            <h1 className="text-2xl font-bold tracking-tight text-gray-900">
              Bienvenido de vuelta
            </h1>
            <p className="text-gray-500 text-sm mt-2 leading-relaxed">
              Inicia sesión para configurar tu asistente
              <br />y ver tu agenda.
            </p>
          </div>

          {error && (
            <div className="p-3 bg-red-100 border border-red-300 rounded-xl">
              <p className="text-sm text-red-800">{error}</p>
            </div>
          )}

          <button
            type="button"
            onClick={handleGoogleLogin}
            disabled={loading}
            className="w-full h-12 flex items-center justify-center gap-3 border border-gray-300 rounded-xl bg-white shadow-sm hover:bg-gray-50 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            <svg className="w-[18px] h-[18px]" viewBox="0 0 24 24">
              <path d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92a5.06 5.06 0 0 1-2.2 3.32v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.1z" fill="#4285F4" />
              <path d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" fill="#34A853" />
              <path d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z" fill="#FBBC05" />
              <path d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z" fill="#EA4335" />
            </svg>
            <span className="text-sm font-semibold text-gray-800">
              {loading ? 'Redirigiendo...' : 'Continuar con Google'}
            </span>
          </button>

          <p className="text-xs text-center text-gray-400">
            Al continuar, aceptas nuestros términos de servicio
          </p>
        </CardBody>
      </Card>

      {/* Trust microcopy */}
      <div className="mt-5 flex items-center justify-center gap-4 text-xs text-gray-500">
        <span className="inline-flex items-center gap-1.5">
          <Lock size={13} /> SSL cifrado
        </span>
        <span className="w-[3px] h-[3px] rounded-full bg-gray-400" />
        <span className="inline-flex items-center gap-1.5">
          <ShieldCheck size={13} /> Datos en México
        </span>
      </div>
    </div>
  )
}
