'use client'

import React, { useState } from 'react'
import { Button } from '@/components/ui/Button'
import { useApi } from '@/lib/api'
import { Check } from 'lucide-react'

/** Google's multi-color "G" — reused from the onboarding connect step. */
function GoogleGlyph({ className = 'w-5 h-5' }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24">
      <path d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92a5.06 5.06 0 0 1-2.2 3.32v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.1z" fill="#4285F4" />
      <path d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" fill="#34A853" />
      <path d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z" fill="#FBBC05" />
      <path d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z" fill="#EA4335" />
    </svg>
  )
}

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
          connected ? 'bg-green-50 border-green-200' : 'bg-gray-50 border-gray-200'
        }`}
      >
        <span
          className={`w-2.5 h-2.5 rounded-full ${connected ? 'bg-green-500' : 'bg-gray-400'}`}
          style={connected ? { boxShadow: '0 0 0 4px rgba(16,185,129,.18)' } : undefined}
        />
        <span
          className={`text-[13px] font-semibold ${connected ? 'text-green-700' : 'text-gray-700'}`}
        >
          {connected ? 'Conectado' : 'No conectado'}
        </span>
      </div>

      <p className="text-sm text-gray-600">
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
              <Check size={16} className="text-primary-600 flex-shrink-0 mt-0.5" strokeWidth={2.6} />
              <span className="text-sm text-gray-700 leading-relaxed">{item}</span>
            </div>
          ))}
        </div>
      )}

      {error && (
        <div className="p-3 bg-red-100 border border-red-300 rounded-xl">
          <p className="text-sm text-red-800">{error}</p>
        </div>
      )}

      {!connected ? (
        <button
          type="button"
          onClick={handleConnect}
          disabled={loading}
          className="w-full sm:w-auto h-12 px-5 flex items-center justify-center gap-3 border border-gray-300 rounded-xl bg-white shadow-sm hover:bg-gray-50 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
        >
          <GoogleGlyph />
          <span className="text-sm font-semibold text-gray-800">
            {loading ? 'Redirigiendo a Google...' : 'Conectar Google Calendar'}
          </span>
        </button>
      ) : confirmingDisconnect ? (
        <div className="p-4 border border-gray-200 rounded-xl space-y-3">
          <p className="text-sm text-gray-700">
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
