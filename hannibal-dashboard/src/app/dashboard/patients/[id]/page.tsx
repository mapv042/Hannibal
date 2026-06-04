'use client'

import React, { useState, useEffect } from 'react'
import { useParams, useRouter } from 'next/navigation'
import { format } from 'date-fns'
import { es } from 'date-fns/locale'
import { useApi } from '@/lib/api'
import { Button } from '@/components/ui/Button'
import { Card, CardBody, CardHeader } from '@/components/ui/Card'
import { StatusBadge } from '@/components/ui/Badge'
import { EmptyState } from '@/components/ui/states/EmptyState'
import { ErrorState } from '@/components/ui/states/ErrorState'
import { Skeleton } from '@/components/ui/states/Skeleton'
import { ArrowLeft, Mail, Phone, Calendar, UserX } from 'lucide-react'
import type { Patient, Appointment } from '@/lib/supabase'

export default function PatientDetailPage() {
  const params = useParams()
  const router = useRouter()
  const patientId = params.id as string

  const [patient, setPatient] = useState<Patient | null>(null)
  const [appointments, setAppointments] = useState<Appointment[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)
  const api = useApi()

  const loadData = React.useCallback(async () => {
    setLoading(true)
    setError(false)
    try {
      const patientResponse = await api.getPatient(patientId)
      if (patientResponse.success && patientResponse.data) {
        setPatient(patientResponse.data)

        // Load appointments for this patient
        const appointmentsResponse = await api.getAppointments(patientResponse.data.office_id)
        if (appointmentsResponse.success && appointmentsResponse.data) {
          const patientAppointments = appointmentsResponse.data.filter(
            (c) => c.patient_id === patientId
          )
          setAppointments(patientAppointments)
        }
      } else {
        setPatient(null)
      }
    } catch (err) {
      console.error('Error loading patient:', err)
      setError(true)
    } finally {
      setLoading(false)
    }
  }, [patientId, api])

  useEffect(() => {
    loadData()
  }, [loadData])

  if (loading) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-9 w-64" />
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <Skeleton className="h-28 w-full rounded-2xl" />
          <Skeleton className="h-28 w-full rounded-2xl" />
          <Skeleton className="h-28 w-full rounded-2xl" />
        </div>
        <Skeleton className="h-64 w-full rounded-2xl" />
      </div>
    )
  }

  if (error) {
    return (
      <div className="space-y-6">
        <Button variant="ghost" size="sm" onClick={() => router.back()} aria-label="Volver">
          <ArrowLeft size={16} />
        </Button>
        <ErrorState onRetry={loadData} />
      </div>
    )
  }

  if (!patient) {
    return (
      <div className="space-y-6">
        <Button variant="ghost" size="sm" onClick={() => router.back()} aria-label="Volver">
          <ArrowLeft size={16} />
        </Button>
        <EmptyState
          icon={UserX}
          title="Paciente no encontrado"
          description="Es posible que el registro se haya eliminado o que el enlace sea incorrecto."
          action={
            <Button variant="secondary" onClick={() => router.push('/dashboard/patients')}>
              Ver todos los pacientes
            </Button>
          }
        />
      </div>
    )
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center gap-3">
        <Button
          variant="ghost"
          size="sm"
          onClick={() => router.back()}
          aria-label="Volver"
        >
          <ArrowLeft size={16} />
        </Button>
        <div>
          <h1 className="text-2xl sm:text-[28px] font-bold tracking-tight text-gray-900 leading-tight">
            {patient.name}
          </h1>
          <p className="text-sm text-gray-500 mt-1">Perfil del paciente</p>
        </div>
      </div>

      {/* Patient Info */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <Card>
          <CardBody className="space-y-2">
            <div className="flex items-center gap-2 text-gray-600 mb-2">
              <Phone size={16} />
              <p className="text-xs font-medium uppercase">Teléfono</p>
            </div>
            <p className="text-lg font-semibold text-gray-900">
              {patient.whatsapp_number}
            </p>
          </CardBody>
        </Card>

        <Card>
          <CardBody className="space-y-2">
            <div className="flex items-center gap-2 text-gray-600 mb-2">
              <Mail size={16} />
              <p className="text-xs font-medium uppercase">Correo</p>
            </div>
            <p className="text-lg font-semibold text-gray-900">
              {patient.email || '-'}
            </p>
          </CardBody>
        </Card>

        <Card>
          <CardBody className="space-y-2">
            <div className="flex items-center gap-2 text-gray-600 mb-2">
              <Calendar size={16} />
              <p className="text-xs font-medium uppercase">Total de citas</p>
            </div>
            <p className="text-lg font-semibold text-gray-900">
              {patient.total_consultations}
            </p>
          </CardBody>
        </Card>
      </div>

      {/* Notes */}
      {patient.notes && (
        <Card>
          <CardHeader>
            <h3 className="font-semibold text-gray-900">Notas</h3>
          </CardHeader>
          <CardBody>
            <p className="text-gray-700">{patient.notes}</p>
          </CardBody>
        </Card>
      )}

      {/* Appointment History */}
      <Card>
        <CardHeader>
          <h3 className="font-semibold text-gray-900">
            Historial de citas ({appointments.length})
          </h3>
        </CardHeader>
        <CardBody>
          {appointments.length === 0 ? (
            <p className="text-gray-600 text-center py-8">Sin citas registradas</p>
          ) : (
            <div className="space-y-3">
              {appointments
                .sort((a, b) => new Date(b.date_time).getTime() - new Date(a.date_time).getTime())
                .map((appointment) => (
                  <div
                    key={appointment.id}
                    className="p-4 border border-gray-200 rounded-lg hover:bg-gray-50 transition-colors"
                  >
                    <div className="flex items-start justify-between mb-2">
                      <div>
                        <p className="font-medium text-gray-900">
                          {format(new Date(appointment.date_time), "MMMM d, yyyy", {
                            locale: es,
                          })}{' '}
                          - {format(new Date(appointment.date_time), 'HH:mm')}
                        </p>
                        <p className="text-sm text-gray-600">
                          {appointment.consultation_type} · {appointment.duration_minutes} min
                        </p>
                      </div>
                      <StatusBadge estado={appointment.status} />
                    </div>
                    {appointment.notes && (
                      <p className="text-sm text-gray-600 mt-2">{appointment.notes}</p>
                    )}
                  </div>
                ))}
            </div>
          )}
        </CardBody>
      </Card>

      {/* Last Appointment */}
      {patient.last_consultation_at && (
        <Card>
          <CardBody className="space-y-1">
            <p className="text-xs font-medium text-gray-600 uppercase">Última cita</p>
            <p className="text-sm text-gray-900">
              {format(new Date(patient.last_consultation_at), 'PPp', {
                locale: es,
              })}
            </p>
          </CardBody>
        </Card>
      )}
    </div>
  )
}
