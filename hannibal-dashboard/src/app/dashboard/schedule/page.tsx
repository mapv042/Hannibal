'use client'

import React, { useState } from 'react'
import { createBrowserSupabaseClient } from '@/lib/supabase'
import { ScheduleCalendar } from '@/components/scheduling/ScheduleCalendar'
import { Modal } from '@/components/ui/Modal'
import { Card, CardBody } from '@/components/ui/Card'
import { StatusBadge } from '@/components/ui/Badge'
import { PageHeader } from '@/components/ui/PageHeader'
import { Skeleton } from '@/components/ui/states/Skeleton'
import { formatDateSafe, patientLabel } from '@/lib/appointments'
import type { Appointment } from '@/lib/supabase'

export default function SchedulePage() {
  const [selectedAppointment, setSelectedAppointment] = useState<Appointment | null>(null)
  const [user, setUser] = useState<any>(null)
  const supabase = createBrowserSupabaseClient()

  React.useEffect(() => {
    const getUser = async () => {
      const {
        data: { user },
      } = await supabase.auth.getUser()
      setUser(user)
    }
    getUser()
  }, [supabase])

  return (
    <div className="space-y-6">
      <PageHeader title="Agenda" subtitle="Consulta y administra tu calendario de citas" />

      {/* Calendar */}
      <Card>
        <CardBody className="p-6">
          {!user ? (
            <Skeleton className="h-[560px] w-full rounded-xl" />
          ) : (
            <ScheduleCalendar
              officeId={user.id}
              onAppointmentClick={setSelectedAppointment}
            />
          )}
        </CardBody>
      </Card>

      {/* Appointment Detail Modal */}
      <Modal
        isOpen={!!selectedAppointment}
        onClose={() => setSelectedAppointment(null)}
        title="Detalles de la cita"
        size="md"
      >
        {selectedAppointment && (
          <div className="space-y-4">
            <div className="space-y-3">
              <div>
                <p className="text-xs font-medium text-gray-600 uppercase">Paciente</p>
                <p className="text-lg font-semibold text-gray-900">
                  {patientLabel(selectedAppointment)}
                </p>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <p className="text-xs font-medium text-gray-600 uppercase">Fecha</p>
                  <p className="text-sm text-gray-900">
                    {formatDateSafe(selectedAppointment.start_datetime, 'MMMM d')}
                  </p>
                </div>
                <div>
                  <p className="text-xs font-medium text-gray-600 uppercase">Hora</p>
                  <p className="text-sm text-gray-900">
                    {formatDateSafe(selectedAppointment.start_datetime, 'HH:mm')}
                  </p>
                </div>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <p className="text-xs font-medium text-gray-600 uppercase">Duración</p>
                  <p className="text-sm text-gray-900">
                    {selectedAppointment.duration_minutes} minutos
                  </p>
                </div>
                <div>
                  <p className="text-xs font-medium text-gray-600 uppercase">Motivo</p>
                  <p className="text-sm text-gray-900">
                    {selectedAppointment.consultation_reason || '—'}
                  </p>
                </div>
              </div>

              <div>
                <p className="text-xs font-medium text-gray-600 uppercase mb-1">
                  Estado
                </p>
                <StatusBadge estado={selectedAppointment.status} />
              </div>

              {selectedAppointment.post_consultation_notes && (
                <div>
                  <p className="text-xs font-medium text-gray-600 uppercase">Notas</p>
                  <p className="text-sm text-gray-700 mt-1">
                    {selectedAppointment.post_consultation_notes}
                  </p>
                </div>
              )}
            </div>

            <div className="pt-4 border-t border-gray-200">
              <p className="text-xs text-gray-500">
                Creada:{' '}
                {formatDateSafe(selectedAppointment.created_at, 'PPp')}
              </p>
            </div>
          </div>
        )}
      </Modal>
    </div>
  )
}
