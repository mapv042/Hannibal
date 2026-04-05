'use client'

import React, { useEffect, useState, useCallback } from 'react'
import FullCalendar from '@fullcalendar/react'
import dayGridPlugin from '@fullcalendar/daygrid'
import timeGridPlugin from '@fullcalendar/timegrid'
import interactionPlugin from '@fullcalendar/interaction'
import { useApi } from '@/lib/api'
import type { Appointment } from '@/lib/supabase'

interface ScheduleCalendarProps {
  officeId: string
  onAppointmentClick?: (appointment: Appointment) => void
  onDateClick?: (date: string) => void
}

type EventStatus = 'confirmed' | 'pending' | 'blocked' | 'no_show' | 'cancelled'

const statusColors: Record<EventStatus, string> = {
  confirmed: '#10b981',
  pending: '#f59e0b',
  blocked: '#6b7280',
  no_show: '#ef4444',
  cancelled: '#ef4444',
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

  const events = appointments.map((appointment) => ({
    id: appointment.id,
    title: appointment.patient_id,
    start: appointment.date_time,
    end: new Date(new Date(appointment.date_time).getTime() + appointment.duration_minutes * 60000).toISOString(),
    backgroundColor: statusColors[appointment.status as EventStatus],
    borderColor: statusColors[appointment.status as EventStatus],
    extendedProps: {
      appointment,
    },
  }))

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
          <p className="text-gray-600">Loading calendar...</p>
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
          locale="en"
          height="auto"
          contentHeight="auto"
        />
      )}
    </div>
  )
}

ScheduleCalendar.displayName = 'ScheduleCalendar'
