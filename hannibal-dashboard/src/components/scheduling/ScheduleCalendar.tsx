'use client'

import React, { useEffect, useState, useCallback } from 'react'
import FullCalendar from '@fullcalendar/react'
import dayGridPlugin from '@fullcalendar/daygrid'
import timeGridPlugin from '@fullcalendar/timegrid'
import interactionPlugin from '@fullcalendar/interaction'
import esLocale from '@fullcalendar/core/locales/es'
import { useApi } from '@/lib/api'
import { getStatus, TONE_HEX } from '@/lib/status'
import { patientLabel, timestampSafe } from '@/lib/appointments'
import type { Appointment } from '@/lib/supabase'

interface ScheduleCalendarProps {
  officeId: string
  onAppointmentClick?: (appointment: Appointment) => void
  onDateClick?: (date: string) => void
}

export const ScheduleCalendar: React.FC<ScheduleCalendarProps> = ({
  officeId,
  onAppointmentClick,
  onDateClick,
}) => {
  const [appointments, setAppointments] = useState<Appointment[]>([])
  const [loading, setLoading] = useState(true)
  const api = useApi()

  const loadAppointments = useCallback(async () => {
    try {
      setLoading(true)
      const response = await api.getAppointments(officeId)
      if (response.success && response.data) {
        setAppointments(response.data)
      }
    } catch (error) {
      console.error('Error loading appointments:', error)
    } finally {
      setLoading(false)
    }
  }, [officeId, api])

  useEffect(() => {
    loadAppointments()
  }, [loadAppointments])

  // An appointment without a usable start can't be placed on a calendar; drop
  // it rather than hand FullCalendar an invalid date it renders at epoch.
  const events = appointments
    .filter((appointment) => timestampSafe(appointment.start_datetime) !== null)
    .map((appointment) => {
      const color = TONE_HEX[getStatus(appointment.status).tone]
      return {
        id: appointment.id,
        title: patientLabel(appointment),
        start: appointment.start_datetime,
        end: appointment.end_datetime,
        backgroundColor: color,
        borderColor: color,
        extendedProps: {
          appointment,
        },
      }
    })

  const handleEventClick = (info: any) => {
    const appointment = info.event.extendedProps.appointment
    onAppointmentClick?.(appointment)
  }

  const handleDateClick = (info: any) => {
    onDateClick?.(info.dateStr)
  }

  return (
    <div className="bg-white rounded-lg border border-gray-200 p-6">
      {loading ? (
        <div className="text-center py-12">
          <p className="text-gray-600">Cargando calendario...</p>
        </div>
      ) : (
        <FullCalendar
          plugins={[dayGridPlugin, timeGridPlugin, interactionPlugin]}
          headerToolbar={{
            left: 'prev,next today',
            center: 'title',
            right: 'dayGridMonth,timeGridWeek,timeGridDay',
          }}
          initialView="timeGridWeek"
          editable={false}
          selectable={true}
          selectMirror={true}
          dayMaxEvents={true}
          weekends={true}
          events={events}
          eventClick={handleEventClick}
          dateClick={handleDateClick}
          locale={esLocale}
          height="auto"
          contentHeight="auto"
        />
      )}
    </div>
  )
}

ScheduleCalendar.displayName = 'ScheduleCalendar'
