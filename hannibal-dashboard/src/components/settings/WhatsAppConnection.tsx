'use client'

import React, { useCallback, useEffect, useState } from 'react'
import { Button } from '@/components/ui/Button'
import { useApi, type WhatsAppStatus } from '@/lib/api'
import { useWhatsAppConnect } from '@/lib/useWhatsAppConnect'

interface WhatsAppConnectionProps {
  officeId: string
}

type Tone = 'ok' | 'wait' | 'bad'

// While WhatsApp reviews the message templates (minutes, usually) the status
// is re-read so the card turns green without a reload.
const RECHECK_MS = 30_000

/**
 * The practice's WhatsApp number and whether the assistant can actually reach
 * patients outside a live chat. Reminders, confirmations and doctor alerts go
 * out as WhatsApp-approved messages created on the doctor's own account after
 * connecting. The token is refreshed automatically; if it is ever lost
 * (revoked, or a refresh failed until it expired) reconnecting here is the
 * way back — the same Embedded Signup flow as onboarding.
 */
export const WhatsAppConnection: React.FC<WhatsAppConnectionProps> = ({ officeId }) => {
  const [status, setStatus] = useState<WhatsAppStatus | null>(null)
  const [justConnected, setJustConnected] = useState(false)
  const { connect, connecting, error } = useWhatsAppConnect(officeId)
  const api = useApi()

  const refresh = useCallback(async () => {
    const res = await api.getWhatsAppStatus(officeId)
    if (res.success && res.data) setStatus(res.data)
  }, [api, officeId])

  useEffect(() => {
    refresh()
  }, [refresh])

  const health = status?.active ? describeHealth(status) : null

  useEffect(() => {
    if (health?.tone !== 'wait') return
    const timer = setInterval(refresh, RECHECK_MS)
    return () => clearInterval(timer)
  }, [health?.tone, refresh])

  const handleConnect = async () => {
    const result = await connect()
    if (result) {
      setJustConnected(true)
      await refresh()
    }
  }

  const connected = Boolean(status?.active)
  const broken = Boolean(status?.token_error)

  return (
    <div className="space-y-4">
      <div className="p-4 bg-gray-50 rounded-xl border border-gray-200 space-y-3">
        <div className="flex items-center justify-between gap-4">
          <div>
            <p className="font-medium text-gray-900">Número de WhatsApp</p>
            <p className="text-sm text-gray-600 mt-1">
              {status === null
                ? 'Cargando…'
                : connected
                  ? status.phone_number || 'Conectado'
                  : 'Sin conectar'}
            </p>
          </div>
          <div
            className={`w-3 h-3 rounded-full flex-shrink-0 ${
              !connected ? 'bg-gray-400' : broken ? 'bg-red-500' : 'bg-green-500'
            }`}
          />
        </div>

        {status !== null && (
          <div className="space-y-2">
            {!connected && (
              <p className="text-sm text-gray-600">
                Conecta el número de tu consultorio para que el asistente empiece a contestar.
                Tus pacientes escriben al mismo número de siempre y tú sigues viendo los chats en
                tu WhatsApp.
              </p>
            )}
            {justConnected && !broken && (
              <p className="text-sm text-green-700">Listo, tu WhatsApp quedó conectado.</p>
            )}
            {error && (
              <div className="p-3 bg-red-50 border border-red-200 rounded-lg">
                <p className="text-sm text-red-800">{error}</p>
              </div>
            )}
            <div className="flex flex-wrap items-center gap-3">
              <Button
                size="sm"
                variant={!connected || broken ? 'primary' : 'secondary'}
                onClick={handleConnect}
                disabled={connecting}
              >
                {connecting
                  ? 'Conectando con Meta…'
                  : connected
                    ? 'Reconectar WhatsApp'
                    : 'Conectar WhatsApp'}
              </Button>
              {connected && !broken && (
                <span className="text-xs text-gray-500">
                  Solo si cambiaste de número o algo dejó de funcionar.
                </span>
              )}
            </div>
          </div>
        )}
      </div>

      {health && (
        <div className="flex items-start justify-between gap-4 p-4 bg-gray-50 rounded-xl border border-gray-200">
          <div>
            <p className="font-medium text-gray-900">Mensajes automáticos</p>
            <p className="text-sm text-gray-600 mt-1">{health.message}</p>
          </div>
          <div
            className={`w-3 h-3 mt-1.5 rounded-full flex-shrink-0 ${
              { ok: 'bg-green-500', wait: 'bg-yellow-500', bad: 'bg-red-500' }[health.tone]
            }`}
          />
        </div>
      )}
    </div>
  )
}

function describeHealth(status: WhatsAppStatus): { tone: Tone; message: string } {
  const { templates } = status
  const problems = Object.keys(templates.problems).length
  const pending = templates.pending.length

  if (status.token_error) {
    return {
      tone: 'bad',
      message:
        'La conexión con WhatsApp dejó de funcionar y el asistente no puede enviar mensajes. ' +
        'Usa «Reconectar WhatsApp» y elige el mismo número; toma un par de minutos.',
    }
  }
  if (!templates.synced_at) {
    return {
      tone: 'wait',
      message: 'Estamos preparando los mensajes automáticos en tu cuenta de WhatsApp.',
    }
  }
  if (problems > 0) {
    return {
      tone: 'bad',
      message: `${problems} de ${templates.total} mensajes automáticos no están disponibles todavía. Ya estamos trabajando en ello.`,
    }
  }
  if (pending > 0) {
    return {
      tone: 'wait',
      message: `WhatsApp está revisando ${pending} de ${templates.total} mensajes automáticos. Suele tardar unos minutos.`,
    }
  }
  return {
    tone: 'ok',
    message: `Los ${templates.total} mensajes automáticos (recordatorios, confirmaciones y avisos para ti) están aprobados por WhatsApp.`,
  }
}
