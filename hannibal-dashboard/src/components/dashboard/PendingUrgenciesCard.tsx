import React from 'react'
import Link from 'next/link'
import { Card, CardBody, CardHeader } from '@/components/ui/Card'
import { formatDateSafe } from '@/lib/appointments'
import { Siren } from 'lucide-react'
import type { PendingUrgency } from '@/lib/api'

interface PendingUrgenciesCardProps {
  urgencies: PendingUrgency[]
}

/**
 * Urgent requests still waiting on the doctor. Read-only on purpose: the doctor
 * answers them on WhatsApp, where the assistant already asked. Hidden when
 * there are none, so an empty card never trains the eye to skip it.
 */
export const PendingUrgenciesCard: React.FC<PendingUrgenciesCardProps> = ({ urgencies }) => {
  if (urgencies.length === 0) return null

  return (
    <Card className="border-red-200">
      <CardHeader className="bg-red-50">
        <div className="flex items-center gap-2.5">
          <Siren size={18} className="text-red-600" aria-hidden="true" />
          <h2 className="text-base font-semibold text-red-900">
            {urgencies.length === 1
              ? '1 solicitud urgente esperando tu respuesta'
              : `${urgencies.length} solicitudes urgentes esperando tu respuesta`}
          </h2>
        </div>
        <p className="text-xs text-red-800 mt-1">
          Respóndele a tu asistente por WhatsApp para aprobarlas o rechazarlas.
        </p>
      </CardHeader>
      <CardBody className="divide-y divide-gray-100 py-0">
        {urgencies.map((u) => (
          <div key={u.id} className="py-3 flex items-start justify-between gap-3">
            <div className="min-w-0">
              <Link
                href={`/dashboard/patients/${u.patient_id}`}
                className="text-sm font-semibold text-gray-900 hover:underline"
              >
                {u.patient_name}
              </Link>
              <p className="text-sm text-gray-700 mt-0.5 break-words">{u.reason}</p>
              <p className="text-xs text-gray-500 mt-0.5">Horario solicitado: {u.preferred}</p>
            </div>
            {u.created_at && (
              <span className="text-xs text-gray-500 flex-shrink-0 tabular-nums">
                {formatDateSafe(u.created_at, 'h:mm a')}
              </span>
            )}
          </div>
        ))}
      </CardBody>
    </Card>
  )
}

PendingUrgenciesCard.displayName = 'PendingUrgenciesCard'
