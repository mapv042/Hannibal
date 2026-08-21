'use client'

import React, { useState } from 'react'
import { Button } from '@/components/ui/Button'
import { useApi } from '@/lib/api'
import { GoogleGlyph } from '@/components/brand/GoogleGlyph'
import { Check } from 'lucide-react'

interface GoogleCalendarIntegrationProps {
  connected: boolean
  /** Called after a successful disconnect so the parent can refresh its office. */
  onDisconnected: () => void
}

export const GoogleCalendarIntegration: React.FC<GoogleCalendarIntegrationProps> = ({
  connected,
  onDisconnected,
}) => {
  const [loading, setLoading] = useState(false)
  const [confirmingDisconnect, setConfirmingDisconnect] = useState(false)
  const [error, setError] = useState('')
  const api = useApi()

  const handleConnect = async () => {
    setError('')
    setLoading(true)
    try {
      const res = await api.getGoogleCalendarAuthUrl('settings')
      if (res.success && res.data?.auth_url) {
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

  const handleDisconnect = async () => {
    setError('')
    setLoading(true)
    try {
      const res = await api.disconnectGoogleCalendar()
      if (res.success) {
        setConfirmingDisconnect(false)
        onDisconnected()
      } else {
        setError(res.error || 'No se pudo desconectar Google Calendar')
      }
    } catch {
      setError('Error al desconectar Google Calendar')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="space-y-4">
      <div
        className={`flex items-center gap-3 px-3.5 py-3 rounded-xl border ${
          connected ? 'bg-green-50 border-green-200' : 'bg-off-white border-line'
        }`}
      >
        <span
          className={`w-2 h-2 rounded-full ${connected ? 'bg-brand-green' : 'bg-slate-light'}`}
        />
        <span
          className={`text-[13px] font-semibold ${connected ? 'text-brand-green' : 'text-slate'}`}
        >
          {connected ? 'Conectado' : 'No conectado'}
        </span>
      </div>

      <p className="text-sm text-slate">
        {connected
          ? 'Las citas que agenda el asistente se crean en tu Google Calendar, y los eventos que ya tengas ahí bloquean esos horarios automáticamente.'
          : 'Conecta Google Calendar para que las citas se creen en tu calendario y el asistente respete los eventos que ya tengas agendados.'}
      </p>

      {!connected && (
        <div className="space-y-2.5">
          {[
            'Citas creadas, modificadas y canceladas en tiempo real',
            'Respeta eventos que ya tengas en el calendario',
            'Funciona con Google Workspace y Gmail personal',
          ].map((item) => (
            <div key={item} className="flex items-start gap-2.5">
              <Check size={16} className="text-accent flex-shrink-0 mt-0.5" strokeWidth={2.6} />
              <span className="text-sm text-slate leading-relaxed">{item}</span>
            </div>
          ))}
        </div>
      )}

      {error && (
        <div className="p-3 bg-red-50 border border-red-200 rounded-lg">
          <p className="text-sm text-red-800">{error}</p>
        </div>
      )}

      {!connected ? (
        <button
          type="button"
          onClick={handleConnect}
          disabled={loading}
          className="w-full sm:w-auto h-12 px-5 flex items-center justify-center gap-3 border border-line rounded-md bg-white hover:border-accent hover:bg-off-white transition-colors disabled:opacity-45 disabled:cursor-not-allowed"
        >
          <GoogleGlyph />
          <span className="text-sm font-semibold text-navy">
            {loading ? 'Redirigiendo a Google…' : 'Conectar Google Calendar'}
          </span>
        </button>
      ) : confirmingDisconnect ? (
        <div className="p-4 border border-line rounded-xl space-y-3">
          <p className="text-sm text-slate">
            Al desconectar, dejamos de sincronizar tu calendario y borramos el acceso que nos
            diste. Las citas ya creadas permanecen en tu Google Calendar.
          </p>
          <div className="flex flex-wrap gap-2">
            <Button variant="danger" onClick={handleDisconnect} isLoading={loading}>
              Sí, desconectar
            </Button>
            <Button
              variant="secondary"
              onClick={() => setConfirmingDisconnect(false)}
              disabled={loading}
            >
              Cancelar
            </Button>
          </div>
        </div>
      ) : (
        <Button variant="secondary" onClick={() => setConfirmingDisconnect(true)}>
          Desconectar Google Calendar
        </Button>
      )}
    </div>
  )
}
