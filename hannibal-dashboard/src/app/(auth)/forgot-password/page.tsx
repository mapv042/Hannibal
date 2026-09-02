'use client'

import React, { useState } from 'react'
import Link from 'next/link'
import { createBrowserSupabaseClient } from '@/lib/supabase'
import { Card, CardBody } from '@/components/ui/Card'
import { Input } from '@/components/ui/Input'
import { Button } from '@/components/ui/Button'
import { Logo } from '@/components/ui/Logo'
import { authErrorMessage } from '@/lib/password'
import { MailCheck } from 'lucide-react'

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [sent, setSent] = useState(false)

  const supabase = createBrowserSupabaseClient()

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    setLoading(true)

    const { error: resetError } = await supabase.auth.resetPasswordForEmail(
      email.trim(),
      {
        // The recovery link carries a code that /auth/callback exchanges for a
        // short-lived session, then forwards to the page where the new password
        // is set. `next` is validated as a same-origin path in that route.
        redirectTo: `${window.location.origin}/auth/callback?next=/update-password`,
      }
    )

    // Only a transport/rate-limit failure is surfaced. An unknown address is
    // reported as success on purpose: a distinct "that email doesn't exist"
    // would turn this form into a way to discover which doctors are customers.
    if (resetError && !resetError.message.toLowerCase().includes('not found')) {
      setError(authErrorMessage(resetError.message))
      setLoading(false)
      return
    }

    setSent(true)
    setLoading(false)
  }

  if (sent) {
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
              Si <strong className="text-navy">{email.trim()}</strong> tiene una cuenta con
              nosotros, te enviamos un enlace para restablecer tu contraseña. El enlace expira en
              una hora.
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
            <h1 className="display text-[26px]">Restablece tu contraseña</h1>
            <p className="text-slate text-sm mt-2.5 leading-relaxed">
              Escribe tu correo y te enviamos un enlace
              <br />
              para crear una nueva.
            </p>
          </div>

          {error && (
            <div className="p-3 bg-red-50 border border-red-200 rounded-lg">
              <p className="text-sm text-red-800">{error}</p>
            </div>
          )}

          <form onSubmit={handleSubmit} className="space-y-4">
            <Input
              label="Correo electrónico"
              type="email"
              name="email"
              autoComplete="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="tu@consultorio.mx"
              disabled={loading}
            />

            <Button
              type="submit"
              size="lg"
              className="w-full"
              isLoading={loading}
              disabled={loading}
            >
              Enviar enlace
            </Button>
          </form>

          <p className="text-sm text-center text-slate">
            <Link href="/login" className="font-semibold text-accent hover:underline">
              Volver a iniciar sesión
            </Link>
          </p>
        </CardBody>
      </Card>
    </div>
  )
}
