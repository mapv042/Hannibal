'use client'

import React from 'react'
import { format } from 'date-fns'
import { es } from 'date-fns/locale'
import { StatusBadge } from '@/components/ui/Badge'
import { Card, CardBody } from '@/components/ui/Card'
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
        <div className="flex items-start justify-between">
          <div>
            <p className="text-sm font-semibold text-gray-900">{time}</p>
            <p className="text-xs text-gray-500 mt-1">{date}</p>
          </div>
          <StatusBadge estado={appointment.status} />
        </div>

        <div className="space-y-1">
          <p className="text-sm font-medium text-gray-900">
            {appointment.patient_id}
          </p>
          <p className="text-xs text-gray-600">{appointment.consultation_type}</p>
        </div>

        <div className="flex items-center justify-between pt-2 border-t border-gray-100">
          <span className="text-xs text-gray-500">
            {appointment.duration_minutes} min
          </span>
          {appointment.notes && (
            <span className="text-xs text-gray-500 truncate">
              {appointment.notes}
            </span>
          )}
        </div>
      </CardBody>
    </Card>
  )
}

AppointmentCard.displayName = 'AppointmentCard'
