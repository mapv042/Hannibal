'use client'

import React from 'react'
import { format } from 'date-fns'
import { es } from 'date-fns/locale'
import { StatusBadge } from '@/components/ui/Badge'
import { Card, CardBody } from '@/components/ui/Card'
import { patientLabel } from '@/lib/appointments'
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
  const time = format(new Date(appointment.date_time), 'HH:mm', { locale: es })
  const date = format(new Date(appointment.date_time), "MMMM d", { locale: es })

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
            <p className="text-xs text-gray-600 mt-0.5">{appointment.consultation_type}</p>
          </div>
          <StatusBadge estado={appointment.status} className="flex-shrink-0" />
        </div>

        <div className="flex items-center justify-between pt-2 border-t border-gray-100">
          <span className="text-xs text-gray-500 tabular-nums">
            {time} · {date} · {appointment.duration_minutes} min
          </span>
          {appointment.notes && (
            <span className="text-xs text-gray-500 truncate max-w-[40%]">
              {appointment.notes}
            </span>
          )}
        </div>
      </CardBody>
    </Card>
  )
}

AppointmentCard.displayName = 'AppointmentCard'
