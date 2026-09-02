'use client'

import React, { useEffect, useState } from 'react'
import { Card, CardBody } from '@/components/ui/Card'
import { Button } from '@/components/ui/Button'
import { StepHeader } from '@/components/onboarding/StepHeader'
import { Check } from 'lucide-react'
import { useApi } from '@/lib/api'
import {
  launchWhatsAppSignup,
  EmbeddedSignupCancelledError,
} from '@/lib/metaEmbeddedSignup'

interface StepConnectWhatsAppProps {
  onNext: () => void
  onBack: () => void
  /** Null in preview mode (no office yet) — the connect button is disabled. */
  officeId: string | null
}

const benefits = [
  'Tus pacientes escriben al mismo número de siempre',
  'Tú sigues viendo todos los chats en tu WhatsApp',
  'El bot solo responde cuando tú no estás respondiendo',
]

export const StepConnectWhatsApp: React.FC<StepConnectWhatsAppProps> = ({
  onNext,
  onBack,
  officeId,
}) => {
  const [connected, setConnected] = useState(false)
  const [phoneNumber, setPhoneNumber] = useState<string | null>(null)
  const [connecting, setConnecting] = useState(false)
  const [error, setError] = useState('')
  const api = useApi()

  // A doctor returning to this step (or reloading) sees their real state.
  useEffect(() => {
    if (!officeId) return
    let cancelled = false
    api.getWhatsAppStatus(officeId).then((res) => {
      if (cancelled || !res.success || !res.data) return
      if (res.data.active) {
        setConnected(true)
        setPhoneNumber(res.data.phone_number)
      }
    })
    return () => {
      cancelled = true
    }
  }, [officeId, api])

  const handleConnect = async () => {
    if (!officeId) return
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
      setConnected(true)
      setPhoneNumber(res.data?.phone_number ?? null)
    } catch (err) {
      if (!(err instanceof EmbeddedSignupCancelledError)) {
        setError(
          err instanceof Error ? err.message : 'Error al conectar WhatsApp'
        )
      }
    } finally {
      setConnecting(false)
    }
  }

  return (
    <Card>
      <CardBody className="p-8">
        <StepHeader
          eyebrow="Paso 5"
          title={connected ? 'WhatsApp conectado' : 'Conecta tu WhatsApp'}
          subtitle={
            connected
              ? 'Tu número quedó conectado. Tus pacientes ya pueden escribirle al asistente.'
              : 'Argos usará el número de tu consultorio. No necesitas otro celular ni cambiar de SIM.'
          }
        />

        <div className="border border-line rounded-xl p-6 mb-6">
          <div
            className="flex items-center gap-3 px-3.5 py-3 rounded-lg mb-4 border"
            style={
              connected
                ? {
                    background: 'rgba(30,138,95,0.07)',
                    borderColor: 'rgba(30,138,95,0.25)',
                  }
                : undefined
            }
          >
            <span
              className={`w-2 h-2 rounded-full ${
                connected ? 'bg-brand-green' : 'bg-slate-light'
              }`}
            />
            <span
              className={`text-[13px] font-semibold ${
                connected ? 'text-brand-green' : 'text-slate'
              }`}
            >
              {connected
                ? `Conectado${phoneNumber ? ` — ${phoneNumber}` : ''}`
                : 'No conectado'}
            </span>
          </div>

          {!connected && (
            <div className="space-y-0">
              {benefits.map((item, i) => (
                <div
                  key={item}
                  className={`flex items-start gap-3 py-2.5 ${
                    i < benefits.length - 1 ? 'border-b border-line' : ''
                  }`}
                >
                  <Check
                    size={16}
                    className="text-brand-green flex-shrink-0 mt-0.5"
                    strokeWidth={2.6}
                  />
                  <span className="text-sm text-slate leading-relaxed">{item}</span>
                </div>
              ))}
            </div>
          )}

          {error && (
            <div className="mt-4 p-3 bg-red-50 border border-red-200 rounded-lg">
              <p className="text-sm text-red-800">{error}</p>
            </div>
          )}

          {!connected && (
            <Button
              variant="secondary"
              className="w-full mt-5"
              onClick={handleConnect}
              disabled={connecting || !officeId}
            >
              {connecting ? 'Conectando con Meta…' : 'Conectar WhatsApp'}
            </Button>
          )}
        </div>

        <div className="flex gap-3">
          <Button variant="secondary" onClick={onBack}>
            Atrás
          </Button>
          <Button onClick={onNext} className="flex-1">
            {connected ? 'Continuar' : 'Omitir por ahora'}
          </Button>
        </div>
      </CardBody>
    </Card>
  )
}
