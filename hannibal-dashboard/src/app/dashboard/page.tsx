'use client'

import React, { useState, useEffect, useCallback } from 'react'
import { format } from 'date-fns'
import { es } from 'date-fns/locale'
import { useApi } from '@/lib/api'
import { createBrowserSupabaseClient } from '@/lib/supabase'
import { AppointmentCard } from '@/components/scheduling/AppointmentCard'
import { Card, CardBody, CardHeader } from '@/components/ui/Card'
import { PageHeader } from '@/components/ui/PageHeader'
import { EmptyState } from '@/components/ui/states/EmptyState'
import { ErrorState } from '@/components/ui/states/ErrorState'
import { SkeletonStats, SkeletonList } from '@/components/ui/states/Skeleton'
import { getStatus } from '@/lib/status'
import { Calendar, CheckCircle, AlertCircle, Users } from 'lucide-react'
import type { Appointment } from '@/lib/supabase'

export default function DashboardPage() {
  const [appointments, setAppointments] = useState<Appointment[]>([])
  const [stats, setStats] = useState({
    total: 0,
    confirmed: 0,
    pending: 0,
    patients: 0,
  })
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)
  const api = useApi()
  const supabase = createBrowserSupabaseClient()

  const loadData = useCallback(async () => {
    setLoading(true)
    setError(false)
    try {
      const {
        data: { user },
      } = await supabase.auth.getUser()

      if (!user) return

      // Load today's appointments
      const appointmentsResponse = await api.getAppointmentsToday(user.id)
      if (appointmentsResponse.success && appointmentsResponse.data) {
        const data = appointmentsResponse.data
        setAppointments(data)

        // Derive counts from the shared status source of truth so the cards
        // always agree with the badges (and don't silently read 0 when the
        // backend label differs from a hard-coded string).
        const confirmed = data.filter((c) => getStatus(c.status).tone === 'success').length
        const pending = data.filter((c) => getStatus(c.status).tone === 'warning').length

        setStats({
          total: data.length,
          confirmed,
          pending,
          patients: new Set(data.map((c) => c.patient_id)).size,
        })
      } else {
        setError(true)
      }
    } catch (err) {
      console.error('Error loading data:', err)
      setError(true)
    } finally {
      setLoading(false)
    }
  }, [api, supabase])

  useEffect(() => {
    loadData()
  }, [loadData])

  const today = format(new Date(), "EEEE d 'de' MMMM, yyyy", { locale: es })
  const capitalizedToday = today.charAt(0).toUpperCase() + today.slice(1)

  const statCards = [
    { label: 'Citas de hoy', value: stats.total, icon: Calendar, tint: 'bg-primary-50', color: 'text-primary-700' },
    { label: 'Confirmadas', value: stats.confirmed, icon: CheckCircle, tint: 'bg-green-50', color: 'text-green-600' },
    { label: 'Sin confirmar', value: stats.pending, icon: AlertCircle, tint: 'bg-yellow-50', color: 'text-yellow-600' },
    { label: 'Pacientes hoy', value: stats.patients, icon: Users, tint: 'bg-blue-50', color: 'text-blue-600' },
  ]

  return (
    <div className="space-y-6">
      <PageHeader title="Hoy" subtitle={capitalizedToday} />

      {/* Stats */}
      {loading ? (
        <SkeletonStats />
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
          {statCards.map(({ label, value, icon: Icon, tint, color }) => (
            <Card key={label}>
              <CardBody className="space-y-2">
                <div className="flex items-center justify-between">
                  <p className="text-sm font-medium text-gray-600">{label}</p>
                  <div className={`w-10 h-10 rounded-[10px] ${tint} flex items-center justify-center`}>
                    <Icon size={20} className={color} />
                  </div>
                </div>
                <p className="text-3xl font-bold text-gray-900 tabular-nums">{value}</p>
              </CardBody>
            </Card>
          ))}
        </div>
      )}

      {/* Appointments */}
      <Card>
        <CardHeader>
          <h2 className="text-lg font-semibold text-gray-900">Agenda del día</h2>
        </CardHeader>
        <CardBody>
          {loading ? (
            <SkeletonList count={3} />
          ) : error ? (
            <ErrorState onRetry={loadData} />
          ) : appointments.length === 0 ? (
            <EmptyState
              icon={Calendar}
              title="No hay citas hoy"
              description="Cuando el asistente agende una cita para hoy, aparecerá aquí."
            />
          ) : (
            <div className="space-y-3">
              {appointments
                .slice()
                .sort((a, b) => new Date(a.date_time).getTime() - new Date(b.date_time).getTime())
                .map((appointment) => (
                  <AppointmentCard key={appointment.id} appointment={appointment} />
                ))}
            </div>
          )}
        </CardBody>
      </Card>
    </div>
  )
}
