import React from 'react'
import { format } from 'date-fns'
import { es } from 'date-fns/locale'
import { Card, CardBody } from '@/components/ui/Card'
import { Clock } from 'lucide-react'
import type { Appointment } from '@/lib/supabase'

interface NextAppointmentCardProps {
  appointment: Appointment | null
  doctorLastName?: string | null
}

/**
 * The one thing the doctor wants on opening the panel: who is next and why.
 *
 * It reuses the same fields as the pre-consultation brief the assistant sends
 * over WhatsApp, so the panel and the phone never disagree about the reason for
 * the visit.
 */
export const NextAppointmentCard: React.FC<NextAppointmentCardProps> = ({
  appointment,
  doctorLastName,
}) => {
  const greeting = doctorLastName ? `Hola, Dr. ${doctorLastName}` : 'Hola'

  if (!appointment) {
    return (
      <Card>
        <CardBody className="flex items-start gap-4">
          <div className="w-10 h-10 rounded-[10px] bg-primary-50 flex items-center justify-center flex-shrink-0">
            <Clock size={20} className="text-primary-700" />
          </div>
          <div>
            <p className="text-sm font-medium text-gray-600">{greeting}</p>
            <p className="text-lg text-gray-900 mt-0.5">
              No te queda ninguna cita hoy.
            </p>
          </div>
        </CardBody>
      </Card>
    )
  }

  const time = format(new Date(appointment.start_datetime), "h:mm a", { locale: es })
  const patient = appointment.patient_name || 'tu paciente'

  return (
    <Card>
      <CardBody className="flex items-start gap-4">
        <div className="w-10 h-10 rounded-[10px] bg-primary-50 flex items-center justify-center flex-shrink-0">
          <Clock size={20} className="text-primary-700" />
        </div>
        <div className="min-w-0">
          <p className="text-sm font-medium text-gray-600">{greeting}</p>
          <p className="text-lg text-gray-900 mt-0.5">
            Tu siguiente cita es <b>{patient}</b> a las <b>{time}</b>
          </p>
          {appointment.consultation_reason && (
            <p className="text-sm text-gray-600 mt-1">
              Motivo: {appointment.consultation_reason}
            </p>
          )}
        </div>
      </CardBody>
    </Card>
  )
}
