'use client'

import React, { useState } from 'react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { createBrowserSupabaseClient } from '@/lib/supabase'
import { Card, CardBody } from '@/components/ui/Card'
import { Input } from '@/components/ui/Input'
import { Button } from '@/components/ui/Button'
import { Logo } from '@/components/ui/Logo'
import { PasswordInput } from '@/components/auth/PasswordInput'
import { GoogleButton, AuthDivider } from '@/components/auth/GoogleButton'
import { authErrorMessage, validatePassword, MIN_PASSWORD_LENGTH } from '@/lib/password'
import { Lock, ShieldCheck, MailCheck } from 'lucide-react'

export default function RegisterPage() {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [loading, setLoading] = useState(false)
  const [googleLoading, setGoogleLoading] = useState(false)
  const [error, setError] = useState('')
  const [emailSent, setEmailSent] = useState(false)

  const router = useRouter()
  const supabase = createBrowserSupabaseClient()

  const handleGoogleSignup = async () => {
    setError('')
    setGoogleLoading(true)
    try {
      const { error: oauthError } = await supabase.auth.signInWithOAuth({
        provider: 'google',
        options: { redirectTo: `${window.location.origin}/auth/callback` },
      })
      if (oauthError) {
        setError(oauthError.message)
        setGoogleLoading(false)
      }
    } catch {
      setError('Error al registrarte con Google. Intenta de nuevo.')
      setGoogleLoading(false)
    }
  }

  const handleSignup = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')

    const passwordError = validatePassword(password)
    if (passwordError) {
      setError(passwordError)
      return
    }
    if (password !== confirm) {
      setError('Las contraseñas no coinciden.')
      return
    }

    setLoading(true)
    const { data, error: signUpError } = await supabase.auth.signUp({
      email: email.trim(),
      password,
      options: { emailRedirectTo: `${window.location.origin}/auth/callback` },
    })

    if (signUpError) {
      setError(authErrorMessage(signUpError.message))
      setLoading(false)
      return
    }

    // When email confirmation is on, Supabase returns a user with no session.
    // It deliberately returns the same shape for an address that already has an
    // account, so we must not branch on "already registered" — doing so would
    // let anyone test which addresses are signed up. Showing "check your inbox"
    // either way is both correct and non-disclosing.
    if (!data.session) {
      setEmailSent(true)
      setLoading(false)
      return
    }

    router.push('/onboarding')
    router.refresh()
  }

  const busy = loading || googleLoading

  if (emailSent) {
    return (
      <div>
        <div className="flex justify-center mb-7">
          <Logo size={36} />
        </div>
        <Card>
          <CardBody className="space-y-5 p-9 text-center">
            <div className="w-12 h-12 rounded-full bg-primary-50 flex items-center justify-center mx-auto">
              <MailCheck size={22} className="text-accent" />
            </div>
            <h1 className="display text-[24px]">Revisa tu correo</h1>
            <p className="text-slate text-sm leading-relaxed">
              Si <strong className="text-navy">{email.trim()}</strong> no tenía una cuenta, te
              enviamos un enlace para confirmarla. Ábrelo desde este mismo dispositivo para
              continuar con la configuración de tu asistente.
            </p>
            <p className="text-[13px] text-slate-light">
              ¿No llegó? Revisa la carpeta de spam antes de intentar de nuevo.
            </p>
            <Link
              href="/login"
              className="inline-block text-sm font-semibold text-accent hover:underline"
            >
              Volver a iniciar sesión
            </Link>
          </CardBody>
        </Card>
      </div>
    )
  }

  return (
    <div>
      <div className="flex justify-center mb-7">
        <Logo size={36} />
      </div>

      <Card>
        <CardBody className="space-y-6 p-9">
          <div className="text-center">
            <h1 className="display text-[26px]">Crea tu cuenta</h1>
            <p className="text-slate text-sm mt-2.5 leading-relaxed">
              Configura tu asistente de WhatsApp
              <br />
              en unos minutos.
            </p>
          </div>

          {error && (
            <div className="p-3 bg-red-50 border border-red-200 rounded-lg">
              <p className="text-sm text-red-800">{error}</p>
            </div>
          )}

          <GoogleButton
            onClick={handleGoogleSignup}
            disabled={busy}
            label={googleLoading ? 'Redirigiendo…' : 'Continuar con Google'}
          />

          <AuthDivider />

          <form onSubmit={handleSignup} className="space-y-4">
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

            <PasswordInput
              label="Contraseña"
              name="password"
              autoComplete="new-password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              helpText={`Mínimo ${MIN_PASSWORD_LENGTH} caracteres. Una frase larga es más segura que una palabra con símbolos.`}
              disabled={busy}
            />

            <PasswordInput
              label="Confirma tu contraseña"
              name="confirmPassword"
              autoComplete="new-password"
              required
              value={confirm}
              onChange={(e) => setConfirm(e.target.value)}
              error={
                confirm.length > 0 && confirm !== password
                  ? 'Las contraseñas no coinciden.'
                  : undefined
              }
              disabled={busy}
            />

            <Button
              type="submit"
              size="lg"
              className="w-full"
              isLoading={loading}
              disabled={busy}
            >
              Crear cuenta
            </Button>
          </form>

          <p className="text-sm text-center text-slate">
            ¿Ya tienes cuenta?{' '}
            <Link href="/login" className="font-semibold text-accent hover:underline">
              Inicia sesión
            </Link>
          </p>

          <p className="text-xs text-center text-slate-light">
            Al crear tu cuenta, aceptas nuestros{' '}
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
