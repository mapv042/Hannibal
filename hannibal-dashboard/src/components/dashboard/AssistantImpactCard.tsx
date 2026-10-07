import React from 'react'
import { Card, CardBody, CardHeader } from '@/components/ui/Card'
import { Clock3, MessageCircle, CalendarCheck, Moon, BellRing } from 'lucide-react'
import type { OfficeStats } from '@/lib/api'

interface AssistantImpactCardProps {
  stats: OfficeStats | null
}

/**
 * What the assistant did on its own this period. The practice-health card
 * answers "how is my agenda doing"; this one answers "is this worth paying
 * for" — in the doctor's currency: time, and patients handled while closed.
 */
export const AssistantImpactCard: React.FC<AssistantImpactCardProps> = ({ stats }) => {
  const a = stats?.assistant
  if (!a) return null

  const nothingYet =
    a.conversations_handled === 0 && a.booked_by_assistant === 0 && a.reminders_sent === 0
  if (nothingYet) return null

  const booked = a.booked_by_assistant + a.rescheduled_by_assistant
  const items = [
    {
      icon: MessageCircle,
      value: a.conversations_handled,
      label: a.conversations_handled === 1 ? 'conversación atendida' : 'conversaciones atendidas',
    },
    {
      icon: CalendarCheck,
      value: booked,
      label:
        a.rescheduled_by_assistant > 0
          ? `citas agendadas o movidas (${a.rescheduled_by_assistant} movidas)`
          : booked === 1
            ? 'cita agendada'
            : 'citas agendadas',
    },
    {
      icon: Moon,
      value: a.after_hours_pct === null ? '—' : `${a.after_hours_pct}%`,
      label: 'de las citas nuevas, fuera de tu horario',
    },
    {
      icon: BellRing,
      value: a.reminders_sent,
      label: a.reminders_sent === 1 ? 'recordatorio enviado' : 'recordatorios enviados',
    },
  ]

  return (
    <Card>
      <CardHeader>
        <h2 className="text-lg font-semibold text-gray-900">Tu asistente, últimos 30 días</h2>
      </CardHeader>
      <CardBody className="space-y-5">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-[10px] bg-primary-50 flex items-center justify-center flex-shrink-0">
            <Clock3 size={20} className="text-primary-700" />
          </div>
          <div>
            <p className="text-3xl font-bold text-gray-900 tabular-nums leading-none">
              ~{a.hours_saved_estimate} h
            </p>
            <p className="text-sm text-gray-600 mt-1">
              de trabajo de recepción que no tuviste que hacer (estimado)
            </p>
          </div>
        </div>

        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          {items.map(({ icon: Icon, value, label }) => (
            <div key={label}>
              <div className="flex items-center gap-2">
                <Icon size={16} className="text-gray-400" aria-hidden="true" />
                <p className="text-2xl font-bold text-gray-900 tabular-nums">{value}</p>
              </div>
              <p className="text-sm text-gray-600">{label}</p>
            </div>
          ))}
        </div>
      </CardBody>
    </Card>
  )
}

AssistantImpactCard.displayName = 'AssistantImpactCard'
