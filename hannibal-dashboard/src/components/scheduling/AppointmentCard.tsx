'use client'

import React from 'react'
import { StatusBadge } from '@/components/ui/Badge'
import { Card, CardBody } from '@/components/ui/Card'
import { formatDateSafe, patientLabel } from '@/lib/appointments'
import { getArrival, TONE_BADGE } from '@/lib/status'
import type { Appointment } from '@/lib/supabase'

interface AppointmentCardProps {
  appointment: Appointment
  onClick?: (appointment: Appointment) => void
  className?: string
}

export const AppointmentCard: React.FC<AppointmentCardProps> = ({
  appointment,
  onClick,
  className = '',
}) => {
  const time = formatDateSafe(appointment.start_datetime, 'HH:mm')
  const date = formatDateSafe(appointment.start_datetime, 'MMMM d')
  // Arrival is a separate axis from status — a confirmed cita can still have a
  // patient stuck in traffic — so it gets its own chip beside the status badge.
  const arrival = getArrival(appointment.arrival_status, appointment.arrival_eta_minutes)
  const ArrivalIcon = arrival?.icon

  return (
    <Card
      onClick={() => onClick?.(appointment)}
      className={`cursor-pointer hover:shadow-md transition-shadow ${className}`}
    >
      <CardBody className="space-y-3">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <p className="text-sm font-semibold text-gray-900 truncate">
              {patientLabel(appointment)}
            </p>
            {appointment.consultation_reason && (
              <p className="text-xs text-gray-600 mt-0.5 truncate">
                {appointment.consultation_reason}
              </p>
            )}
          </div>
          <div className="flex items-center gap-1.5 flex-shrink-0">
            {arrival && ArrivalIcon && (
              <span
                className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-medium ${TONE_BADGE[arrival.tone]}`}
              >
                <ArrivalIcon size={11} aria-hidden="true" />
                {arrival.label}
              </span>
            )}
            <StatusBadge estado={appointment.status} />
          </div>
        </div>

        <div className="flex items-center justify-between pt-2 border-t border-gray-100">
          <span className="text-xs text-gray-500 tabular-nums">
            {time} · {date} · {appointment.duration_minutes} min
          </span>
          {appointment.post_consultation_notes && (
            <span className="text-xs text-gray-500 truncate max-w-[40%]">
              {appointment.post_consultation_notes}
            </span>
          )}
        </div>
      </CardBody>
    </Card>
  )
}

AppointmentCard.displayName = 'AppointmentCard'
