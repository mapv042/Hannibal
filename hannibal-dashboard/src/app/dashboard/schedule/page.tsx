'use client'

import React, { useState } from 'react'
import { createBrowserSupabaseClient } from '@/lib/supabase'
import { ScheduleCalendar } from '@/components/scheduling/ScheduleCalendar'
import { Modal } from '@/components/ui/Modal'
import { Card, CardBody } from '@/components/ui/Card'
import { StatusBadge } from '@/components/ui/Badge'
import { format } from 'date-fns'
import { es } from 'date-fns/locale'
import type { Appointment } from '@/lib/supabase'
// import { X } from 'lucide-react'

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

  if (!user) {
    return <div>Loading...</div>
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-3xl font-bold text-gray-900">Schedule</h1>
        <p className="text-gray-600 mt-1">View and manage your appointment calendar</p>
      </div>

      {/* Calendar */}
      <Card>
        <CardBody className="p-6">
          <ScheduleCalendar
            officeId={user.id}
            onAppointmentClick={setSelectedAppointment}
          />
        </CardBody>
      </Card>

      {/* Appointment Detail Modal */}
      <Modal
        isOpen={!!selectedAppointment}
        onClose={() => setSelectedAppointment(null)}
        title="Appointment Details"
        size="md"
      >
        {selectedAppointment && (
          <div className="space-y-4">
            <div className="space-y-3">
              <div>
                <p className="text-xs font-medium text-gray-600 uppercase">Patient</p>
                <p className="text-lg font-semibold text-gray-900">
                  {selectedAppointment.patient_id}
                </p>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <p className="text-xs font-medium text-gray-600 uppercase">Date</p>
                  <p className="text-sm text-gray-900">
                    {format(new Date(selectedAppointment.date_time), "MMMM d", {
                      locale: es,
                    })}
                  </p>
                </div>
                <div>
                  <p className="text-xs font-medium text-gray-600 uppercase">Time</p>
                  <p className="text-sm text-gray-900">
                    {format(new Date(selectedAppointment.date_time), 'HH:mm', { locale: es })}
                  </p>
                </div>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <p className="text-xs font-medium text-gray-600 uppercase">Duration</p>
                  <p className="text-sm text-gray-900">
                    {selectedAppointment.duration_minutes} minutes
                  </p>
                </div>
                <div>
                  <p className="text-xs font-medium text-gray-600 uppercase">Type</p>
                  <p className="text-sm text-gray-900">
                    {selectedAppointment.consultation_type}
                  </p>
                </div>
              </div>

              <div>
                <p className="text-xs font-medium text-gray-600 uppercase mb-1">
                  Status
                </p>
                <StatusBadge estado={selectedAppointment.status} />
              </div>

              {selectedAppointment.notes && (
                <div>
                  <p className="text-xs font-medium text-gray-600 uppercase">Notes</p>
                  <p className="text-sm text-gray-700 mt-1">
                    {selectedAppointment.notes}
                  </p>
                </div>
              )}
            </div>

            <div className="pt-4 border-t border-gray-200">
              <p className="text-xs text-gray-500">
                Created:{' '}
                {format(new Date(selectedAppointment.created_at), 'PPp', {
                  locale: es,
                })}
              </p>
            </div>
          </div>
        )}
      </Modal>
    </div>
  )
}
