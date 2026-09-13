import React from 'react'
import { Card, CardBody, CardHeader } from '@/components/ui/Card'
import { TrendingDown, TrendingUp } from 'lucide-react'
import type { OfficeStats } from '@/lib/api'

interface PracticeHealthCardProps {
  stats: OfficeStats | null
}

const PERIOD_LABEL: Record<string, string> = {
  week: 'Esta semana',
  month: 'Este mes',
  quarter: 'Este trimestre',
}

const PREVIOUS_LABEL: Record<string, string> = {
  week: 'la semana pasada',
  month: 'el mes pasado',
  quarter: 'el trimestre pasado',
}

/**
 * Turns the assistant's silent work into something the doctor can judge.
 *
 * Kept to three numbers and one trend line on purpose: a panel crowded with
 * metrics gets ignored, and then the doctor has no idea whether any of this is
 * working. A rate the period can't support renders as "—", never as 0%, which
 * would read as a failure rather than as "nothing to measure yet".
 */
export const PracticeHealthCard: React.FC<PracticeHealthCardProps> = ({ stats }) => {
  if (!stats) return null

  const periodLabel = PERIOD_LABEL[stats.period] ?? 'Este mes'
  const previousLabel = PREVIOUS_LABEL[stats.period] ?? 'el periodo pasado'
  const pct = (value: number | null) => (value === null ? '—' : `${value}%`)

  const up = (stats.change_pct ?? 0) >= 0
  const TrendIcon = up ? TrendingUp : TrendingDown

  return (
    <Card>
      <CardHeader>
        <h2 className="text-lg font-semibold text-gray-900">Salud del consultorio</h2>
      </CardHeader>
      <CardBody className="space-y-5">
        <div>
          <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
            <p className="text-3xl font-bold text-gray-900 tabular-nums">
              {stats.total_appointments}
            </p>
            <p className="text-sm text-gray-600">
              {periodLabel}
              {stats.total_appointments === 1 ? ' · 1 cita' : ' · citas'}
            </p>
          </div>
          {stats.change_pct !== null && (
            <p
              className={`mt-1 inline-flex items-center gap-1.5 text-sm ${
                up ? 'text-green-600' : 'text-yellow-600'
              }`}
            >
              <TrendIcon size={15} />
              {up ? '+' : ''}
              {stats.change_pct}% vs {previousLabel}
            </p>
          )}
        </div>

        <div className="grid grid-cols-2 gap-4">
          <div>
            <p className="text-2xl font-bold text-gray-900 tabular-nums">
              {pct(stats.confirmation_rate)}
            </p>
            <p className="text-sm text-gray-600">confirman su cita</p>
          </div>
          <div>
            <p className="text-2xl font-bold text-gray-900 tabular-nums">
              {pct(stats.no_show_rate)}
            </p>
            <p className="text-sm text-gray-600">no se presentaron</p>
          </div>
        </div>
      </CardBody>
    </Card>
  )
}
