'use client'

import { useCallback, useState } from 'react'
import { useApi } from '@/lib/api'
import { launchWhatsAppSignup, EmbeddedSignupCancelledError } from '@/lib/metaEmbeddedSignup'

/**
 * Runs Meta's Embedded Signup and hands the result to the backend — the one
 * flow behind both "Conectar WhatsApp" in onboarding and "Reconectar" in
 * Settings. Reconnecting is the same flow: it issues a fresh token (the only
 * way back once one expires or is revoked) and the backend re-creates any
 * missing message templates on the account.
 *
 * `connect` resolves to the connected display number, or null when the doctor
 * closed the popup or it failed (then `error` says why).
 */
export function useWhatsAppConnect(officeId: string | null) {
  const [connecting, setConnecting] = useState(false)
  const [error, setError] = useState('')
  const api = useApi()

  const connect = useCallback(async (): Promise<{ phoneNumber: string | null } | null> => {
    if (!officeId) return null
    setError('')
    setConnecting(true)
    try {
      const signup = await launchWhatsAppSignup('coexistence')
      const res = await api.completeWhatsAppSignup({
        office_id: officeId,
        code: signup.code,
        phone_number_id: signup.phoneNumberId,
        waba_id: signup.wabaId,
        mode: 'coexistence',
      })
      if (!res.success) {
        throw new Error(res.error || 'No se pudo completar la conexión')
      }
      return { phoneNumber: res.data?.phone_number ?? null }
    } catch (err) {
      if (!(err instanceof EmbeddedSignupCancelledError)) {
        setError(err instanceof Error ? err.message : 'Error al conectar WhatsApp')
      }
      return null
    } finally {
      setConnecting(false)
    }
  }, [api, officeId])

  return { connect, connecting, error }
}
