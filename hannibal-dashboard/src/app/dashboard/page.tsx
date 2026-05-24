'use client'

import React, { useState, useEffect } from 'react'
import { format } from 'date-fns'
import { es } from 'date-fns/locale'
import { useApi } from '@/lib/api'
import { createBrowserSupabaseClient } from '@/lib/supabase'
import { AppointmentCard } from '@/components/scheduling/AppointmentCard'
import { Card, CardBody, CardHeader } from '@/components/ui/Card'
import { Badge } from '@/components/ui/Badge'
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
  const api = useApi()
  const supabase = createBrowserSupabaseClient()

  useEffect(() => {
    const loadData = async () => {
      try {
        const {
          data: { user },
        } = await supabase.auth.getUser()

        if (!user) return

        // Load today's appointments
        const appointmentsResponse = await api.getAppointmentsToday(user.id)
        if (appointmentsResponse.success && appointmentsResponse.data) {
          setAppointments(appointmentsResponse.data)

          const confirmed = appointmentsResponse.data.filter(
            (c) => c.status === 'confirmed'
          ).length
          const pending = appointmentsResponse.data.filter(
            (c) => c.status === 'pending'
          ).length

          setStats({
            total: appointmentsResponse.data.length,
            confirmed,
            pending,
            patients: new Set(appointmentsResponse.data.map((c) => c.patient_id)).size,
          })
        }
      } catch (error) {
        console.error('Error loading data:', error)
      } finally {
        setLoading(false)
      }
    }

    loadData()
  }, [api, supabase])

  const today = format(new Date(), "MMMM d, yyyy", { locale: es })

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <Badge variant="primary" className="mb-3">Panel</Badge>
        <h1 className="text-[28px] font-bold tracking-tight text-gray-900">Hoy</h1>
        <p className="text-sm text-gray-500 mt-1">{today}</p>
      </div>

      {/* Stats Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        <Card>
          <CardBody className="space-y-2">
            <div className="flex items-center justify-between">
              <p className="text-sm font-medium text-gray-600">Citas de hoy</p>
              <div className="w-10 h-10 rounded-[10px] bg-primary-50 flex items-center justify-center">
                <Calendar size={20} className="text-primary-700" />
              </div>
            </div>
            <p className="text-3xl font-bold text-gray-900">{stats.total}</p>
          </CardBody>
        </Card>

        <Card>
          <CardBody className="space-y-2">
            <div className="flex items-center justify-between">
              <p className="text-sm font-medium text-gray-600">Confirmadas</p>
              <div className="w-10 h-10 rounded-[10px] bg-green-50 flex items-center justify-center">
                <CheckCircle size={20} className="text-green-600" />
              </div>
            </div>
            <p className="text-3xl font-bold text-gray-900">{stats.confirmed}</p>
          </CardBody>
        </Card>

        <Card>
          <CardBody className="space-y-2">
            <div className="flex items-center justify-between">
              <p className="text-sm font-medium text-gray-600">Pendientes</p>
              <div className="w-10 h-10 rounded-[10px] bg-yellow-50 flex items-center justify-center">
                <AlertCircle size={20} className="text-yellow-600" />
              </div>
            </div>
            <p className="text-3xl font-bold text-gray-900">{stats.pending}</p>
          </CardBody>
        </Card>

        <Card>
          <CardBody className="space-y-2">
            <div className="flex items-center justify-between">
              <p className="text-sm font-medium text-gray-600">Pacientes</p>
              <div className="w-10 h-10 rounded-[10px] bg-blue-50 flex items-center justify-center">
                <Users size={20} className="text-blue-600" />
              </div>
            </div>
            <p className="text-3xl font-bold text-gray-900">{stats.patients}</p>
          </CardBody>
        </Card>
      </div>

      {/* Appointments List */}
      <div>
        <Card>
          <CardHeader>
            <h2 className="text-xl font-semibold text-gray-900">
              Citas de hoy
            </h2>
          </CardHeader>
          <CardBody>
            {loading ? (
              <div className="text-center py-12">
                <p className="text-gray-600">Cargando citas...</p>
              </div>
            ) : appointments.length === 0 ? (
              <div className="text-center py-12">
                <Calendar size={48} className="mx-auto text-gray-300 mb-4" />
                <p className="text-gray-600">No hay citas hoy</p>
              </div>
            ) : (
              <div className="space-y-3">
                {appointments
                  .sort((a, b) => new Date(a.date_time).getTime() - new Date(b.date_time).getTime())
                  .map((appointment) => (
                    <AppointmentCard key={appointment.id} appointment={appointment} />
                  ))}
              </div>
            )}
          </CardBody>
        </Card>
      </div>
    </div>
  )
}
