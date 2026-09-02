'use client'

import React, { useEffect, useState } from 'react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { createBrowserSupabaseClient } from '@/lib/supabase'
import { Card, CardBody } from '@/components/ui/Card'
import { Input } from '@/components/ui/Input'
import { Button } from '@/components/ui/Button'
import { Logo } from '@/components/ui/Logo'
import { PasswordInput } from '@/components/auth/PasswordInput'
import { GoogleButton, AuthDivider } from '@/components/auth/GoogleButton'
import { authErrorMessage } from '@/lib/password'
import { Lock, ShieldCheck } from 'lucide-react'

export default function LoginPage() {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [loading, setLoading] = useState(false)
  const [googleLoading, setGoogleLoading] = useState(false)
  const [error, setError] = useState('')

  const router = useRouter()
  const supabase = createBrowserSupabaseClient()

  // Surface a failed OAuth exchange, which redirects here with ?error=auth.
  // Read from window rather than useSearchParams to avoid needing a Suspense
  // boundary around this page.
  useEffect(() => {
    if (new URLSearchParams(window.location.search).get('error') === 'auth') {
      setError('No pudimos completar el inicio de sesión. Intenta de nuevo.')
    }
  }, [])

  const handleGoogleLogin = async () => {
    setError('')
    setGoogleLoading(true)
    try {
      const { error: oauthError } = await supabase.auth.signInWithOAuth({
        provider: 'google',
        options: {
          redirectTo: `${window.location.origin}/auth/callback`,
        },
      })
      if (oauthError) {
        setError(oauthError.message)
        setGoogleLoading(false)
      }
    } catch {
      setError('Error al iniciar sesión con Google. Intenta de nuevo.')
      setGoogleLoading(false)
    }
  }

  const handlePasswordLogin = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    setLoading(true)

    // No client-side password validation here on purpose: rules change over
    // time, and telling someone their existing password is "too short" at the
    // sign-in screen is both useless and a hint to an attacker.
    const { error: signInError } = await supabase.auth.signInWithPassword({
      email: email.trim(),
      password,
    })

    if (signInError) {
      setError(authErrorMessage(signInError.message))
      setLoading(false)
      return
    }

    // DashboardShell forwards to /onboarding when setup is still pending.
    router.push('/dashboard')
    router.refresh()
  }

  const busy = loading || googleLoading

  return (
    <div>
      <div className="flex justify-center mb-7">
        <Logo size={36} />
      </div>

      <Card>
        <CardBody className="space-y-6 p-9">
          <div className="text-center">
            <h1 className="display text-[26px]">Bienvenido de vuelta</h1>
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

          <GoogleButton
            onClick={handleGoogleLogin}
            disabled={busy}
            label={googleLoading ? 'Redirigiendo…' : 'Continuar con Google'}
          />

          <AuthDivider />

          <form onSubmit={handlePasswordLogin} className="space-y-4">
            <Input
              label="Correo electrónico"
              type="email"
              name="email"
              autoComplete="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="tu@consultorio.mx"
              disabled={busy}
            />

            <div>
              <PasswordInput
                label="Contraseña"
                name="password"
                autoComplete="current-password"
                required
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                disabled={busy}
              />
              <div className="mt-2 text-right">
                <Link
                  href="/forgot-password"
                  className="text-[13px] text-slate hover:text-accent underline"
                >
                  ¿Olvidaste tu contraseña?
                </Link>
              </div>
            </div>

            <Button
              type="submit"
              size="lg"
              className="w-full"
              isLoading={loading}
              disabled={busy}
            >
              Iniciar sesión
            </Button>
          </form>

          <p className="text-sm text-center text-slate">
            ¿No tienes cuenta?{' '}
            <Link href="/register" className="font-semibold text-accent hover:underline">
              Crear una
            </Link>
          </p>

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
