'use client'

import React, { useEffect, useState } from 'react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { createBrowserSupabaseClient } from '@/lib/supabase'
import { Card, CardBody } from '@/components/ui/Card'
import { Button } from '@/components/ui/Button'
import { Logo } from '@/components/ui/Logo'
import { PasswordInput } from '@/components/auth/PasswordInput'
import { authErrorMessage, validatePassword, MIN_PASSWORD_LENGTH } from '@/lib/password'

/**
 * Where a password-recovery link lands, after /auth/callback has exchanged the
 * code for a session. Reaching this page therefore already proves control of
 * the mailbox — that recovery session is the authorisation, so no current
 * password is asked for (the user by definition doesn't have one).
 */
export default function UpdatePasswordPage() {
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [loading, setLoading] = useState(false)
  const [checking, setChecking] = useState(true)
  const [authorized, setAuthorized] = useState(false)
  const [error, setError] = useState('')
  const [done, setDone] = useState(false)

  const router = useRouter()
  const supabase = createBrowserSupabaseClient()

  // Without a session the link was never valid, already used, or expired.
  // Say so instead of showing a form that cannot possibly succeed.
  useEffect(() => {
    supabase.auth.getSession().then(({ data }) => {
      setAuthorized(!!data.session)
      setChecking(false)
    })
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  const handleSubmit = async (e: React.FormEvent) => {
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
    const { error: updateError } = await supabase.auth.updateUser({ password })

    if (updateError) {
      setError(authErrorMessage(updateError.message))
      setLoading(false)
      return
    }

    // Drop the recovery session so the emailed link cannot be reused, and make
    // the person sign in once with the new password.
    await supabase.auth.signOut()
    setDone(true)
    setLoading(false)
  }

  if (checking) {
    return (
      <div className="text-center py-16">
        <div className="w-10 h-10 rounded-full border-4 border-primary-200 border-t-primary-600 animate-spin mx-auto mb-4" />
        <p className="text-slate text-sm">Verificando el enlace…</p>
      </div>
    )
  }

  if (done) {
    return (
      <div>
        <div className="flex justify-center mb-7">
          <Logo size={36} />
        </div>
        <Card>
          <CardBody className="space-y-5 p-9 text-center">
            <h1 className="display text-[24px]">Contraseña actualizada</h1>
            <p className="text-slate text-sm leading-relaxed">
              Ya puedes iniciar sesión con tu nueva contraseña.
            </p>
            <Button size="lg" className="w-full" onClick={() => router.push('/login')}>
              Iniciar sesión
            </Button>
          </CardBody>
        </Card>
      </div>
    )
  }

  if (!authorized) {
    return (
      <div>
        <div className="flex justify-center mb-7">
          <Logo size={36} />
        </div>
        <Card>
          <CardBody className="space-y-5 p-9 text-center">
            <h1 className="display text-[24px]">Enlace inválido o expirado</h1>
            <p className="text-slate text-sm leading-relaxed">
              Este enlace ya se usó o venció. Solicita uno nuevo para restablecer tu contraseña.
            </p>
            <Link
              href="/forgot-password"
              className="inline-block text-sm font-semibold text-accent hover:underline"
            >
              Solicitar un enlace nuevo
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
            <h1 className="display text-[26px]">Nueva contraseña</h1>
            <p className="text-slate text-sm mt-2.5 leading-relaxed">
              Elige una contraseña para tu cuenta.
            </p>
          </div>

          {error && (
            <div className="p-3 bg-red-50 border border-red-200 rounded-lg">
              <p className="text-sm text-red-800">{error}</p>
            </div>
          )}

          <form onSubmit={handleSubmit} className="space-y-4">
            <PasswordInput
              label="Nueva contraseña"
              name="password"
              autoComplete="new-password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              helpText={`Mínimo ${MIN_PASSWORD_LENGTH} caracteres.`}
              disabled={loading}
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
              disabled={loading}
            />

            <Button
              type="submit"
              size="lg"
              className="w-full"
              isLoading={loading}
              disabled={loading}
            >
              Guardar contraseña
            </Button>
          </form>
        </CardBody>
      </Card>
    </div>
  )
}
