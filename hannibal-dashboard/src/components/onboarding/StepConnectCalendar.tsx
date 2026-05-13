'use client'

import React, { useState } from 'react'
import { Card, CardBody } from '@/components/ui/Card'
import { Button } from '@/components/ui/Button'
import { Calendar, CheckCircle } from 'lucide-react'
import { useApi } from '@/lib/api'

interface StepConnectCalendarProps {
  onNext: () => void
  onBack: () => void
  connected: boolean
}

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
        // Redirect to Google OAuth — callback will return to /onboarding?gcal=success
        window.location.href = res.data.auth_url
      } else {
        setError(res.error || 'No se pudo obtener la URL de autorizacion')
        setLoading(false)
      }
    } catch {
      setError('Error al conectar con Google Calendar')
      setLoading(false)
    }
  }

  return (
    <Card>
      <CardBody className="text-center py-12 px-8">
        <div className={`w-16 h-16 rounded-full flex items-center justify-center mx-auto mb-6 ${
          connected ? 'bg-green-100' : 'bg-blue-100'
        }`}>
          {connected ? (
            <CheckCircle className="w-8 h-8 text-green-600" />
          ) : (
            <Calendar className="w-8 h-8 text-blue-600" />
          )}
        </div>

        <h2 className="text-xl font-bold text-gray-900 mb-2">
          {connected ? 'Google Calendar conectado' : 'Conecta tu calendario'}
        </h2>
        <p className="text-gray-600 mb-8 max-w-md mx-auto">
          {connected
            ? 'Tu Google Calendar esta sincronizado. Las citas apareceran automaticamente en tu calendario.'
            : 'Sincroniza tu Google Calendar para ver tus citas directamente en la app de calendario de tu telefono. Es opcional pero muy recomendado.'}
        </p>

        {!connected && (
          <div className="bg-gray-50 rounded-lg p-5 mb-8 text-left max-w-sm mx-auto space-y-3">
            {[
              'Ve tus citas en la app de calendario de tu telefono',
              'Evita conflictos de horario automaticamente',
              'Nunca se duplicara una cita',
              'Tus datos son privados y seguros',
            ].map((item) => (
              <div key={item} className="flex items-center gap-2">
                <span className="text-blue-500 text-sm font-bold">&#10003;</span>
                <span className="text-sm text-gray-700">{item}</span>
              </div>
            ))}
          </div>
        )}

        {error && (
          <div className="mb-6 p-3 bg-red-100 border border-red-300 rounded-lg max-w-sm mx-auto">
            <p className="text-sm text-red-800">{error}</p>
          </div>
        )}

        {!connected && (
          <button
            type="button"
            onClick={handleConnect}
            disabled={loading}
            className="w-full max-w-sm flex items-center justify-center gap-3 px-4 py-3 border border-gray-300 rounded-lg bg-white hover:bg-gray-50 transition-colors disabled:opacity-50 disabled:cursor-not-allowed mb-6 mx-auto"
          >
            <svg className="w-5 h-5" viewBox="0 0 24 24">
              <path d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92a5.06 5.06 0 0 1-2.2 3.32v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.1z" fill="#4285F4" />
              <path d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" fill="#34A853" />
              <path d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z" fill="#FBBC05" />
              <path d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z" fill="#EA4335" />
            </svg>
            <span className="text-sm font-medium text-gray-700">
              {loading ? 'Redirigiendo a Google...' : 'Conectar Google Calendar'}
            </span>
          </button>
        )}

        <div className="flex gap-3 max-w-sm mx-auto">
          <Button variant="secondary" onClick={onBack}>
            Atras
          </Button>
          <Button onClick={onNext} className="flex-1">
            {connected ? 'Continuar' : 'Omitir por ahora'}
          </Button>
        </div>
      </CardBody>
    </Card>
  )
}
