'use client'

import React, { useState } from 'react'
import { Card, CardBody } from '@/components/ui/Card'
import { Button } from '@/components/ui/Button'
import { StepHeader } from '@/components/onboarding/StepHeader'
import { GoogleGlyph } from '@/components/brand/GoogleGlyph'
import { Check } from 'lucide-react'
import { useApi } from '@/lib/api'

interface StepConnectCalendarProps {
  onNext: () => void
  onBack: () => void
  connected: boolean
}

const BENEFITS = [
  'Citas creadas, modificadas y canceladas en tiempo real',
  'Respeta eventos que ya tengas en el calendario',
  'Funciona con Google Workspace y Gmail personal',
]

export const StepConnectCalendar: React.FC<StepConnectCalendarProps> = ({
  onNext,
  onBack,
  connected,
}) => {
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const api = useApi()

  const handleConnect = async () => {
    setError('')
    setLoading(true)
    try {
      const res = await api.getGoogleCalendarAuthUrl()
      if (res.success && res.data?.auth_url) {
        // Redirect to Google OAuth — callback returns to /onboarding?gcal=success
        window.location.href = res.data.auth_url
      } else {
        setError(res.error || 'No se pudo obtener la URL de autorización')
        setLoading(false)
      }
    } catch {
      setError('Error al conectar con Google Calendar')
      setLoading(false)
    }
  }

  return (
    <Card>
      <CardBody className="p-8">
        <StepHeader
          eyebrow="Paso 6"
          title={connected ? 'Google Calendar conectado' : 'Conecta tu calendario'}
          subtitle={
            connected
              ? 'Tu Google Calendar está sincronizado. Las citas aparecerán automáticamente en tu calendario.'
              : 'Cada cita agendada por el asistente aparece automáticamente en tu calendario. Y respeta los eventos que ya tengas.'
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
              {connected ? 'Conectado' : 'No conectado'}
            </span>
          </div>

          {!connected && (
            <div className="space-y-2.5 mb-5">
              {BENEFITS.map((item) => (
                <div key={item} className="flex items-start gap-2.5">
                  <Check
                    size={16}
                    className="text-accent flex-shrink-0 mt-0.5"
                    strokeWidth={2.6}
                  />
                  <span className="text-sm text-slate leading-relaxed">{item}</span>
                </div>
              ))}
            </div>
          )}

          {error && (
            <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg">
              <p className="text-sm text-red-800">{error}</p>
            </div>
          )}

          {!connected && (
            <button
              type="button"
              onClick={handleConnect}
              disabled={loading}
              className="w-full h-12 flex items-center justify-center gap-3 border border-line rounded-md bg-white hover:border-accent hover:bg-off-white transition-colors disabled:opacity-45 disabled:cursor-not-allowed"
            >
              <GoogleGlyph />
              <span className="text-sm font-semibold text-navy">
                {loading ? 'Redirigiendo a Google…' : 'Conectar Google Calendar'}
              </span>
            </button>
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
