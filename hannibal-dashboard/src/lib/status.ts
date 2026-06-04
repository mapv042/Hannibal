import {
  CheckCircle2,
  Clock,
  XCircle,
  Ban,
  CalendarCheck,
  CircleSlash,
  Circle,
  type LucideIcon,
} from 'lucide-react'

/**
 * Single source of truth for status presentation.
 *
 * The backend enum (see CLAUDE.md / constants.py) is:
 *   scheduled · confirmed · cancelled · completed · no_show
 * Legacy frontend values (pending, blocked) and Spanish aliases are also
 * accepted so nothing ever falls through to an undefined colour/label.
 *
 * This only maps a status string to how it LOOKS. It does not change which
 * statuses the app reads or writes — business logic is untouched.
 */

export type StatusTone = 'success' | 'warning' | 'error' | 'info' | 'neutral'

export interface StatusConfig {
  label: string
  tone: StatusTone
  icon: LucideIcon
}

const STATUS: Record<string, StatusConfig> = {
  // Appointment statuses (backend enum)
  scheduled: { label: 'Sin confirmar', tone: 'warning', icon: Clock },
  confirmed: { label: 'Confirmada', tone: 'success', icon: CheckCircle2 },
  completed: { label: 'Completada', tone: 'neutral', icon: CalendarCheck },
  cancelled: { label: 'Cancelada', tone: 'error', icon: XCircle },
  no_show: { label: 'No asistió', tone: 'error', icon: CircleSlash },
  // Legacy / additional frontend values
  pending: { label: 'Sin confirmar', tone: 'warning', icon: Clock },
  blocked: { label: 'Bloqueada', tone: 'info', icon: Ban },
  // Bot statuses
  active: { label: 'Activo', tone: 'success', icon: CheckCircle2 },
  paused: { label: 'Pausado', tone: 'warning', icon: Clock },
  inactive: { label: 'Inactivo', tone: 'error', icon: CircleSlash },
}

// Spanish aliases → canonical key
const ALIAS: Record<string, string> = {
  confirmada: 'confirmed',
  pendiente: 'scheduled',
  cancelada: 'cancelled',
  bloqueada: 'blocked',
  no_presentado: 'no_show',
  completada: 'completed',
  activo: 'active',
  pausado: 'paused',
  inactivo: 'inactive',
}

const UNKNOWN: StatusConfig = { label: '—', tone: 'neutral', icon: Circle }

export function getStatus(raw?: string | null): StatusConfig {
  if (!raw) return UNKNOWN
  const key = ALIAS[raw] ?? raw
  return STATUS[key] ?? { label: raw, tone: 'neutral', icon: Circle }
}

/** Tailwind classes for a soft badge of each tone. */
export const TONE_BADGE: Record<StatusTone, string> = {
  success: 'bg-green-100 text-green-800',
  warning: 'bg-yellow-100 text-yellow-800',
  error: 'bg-red-100 text-red-800',
  info: 'bg-blue-100 text-blue-800',
  neutral: 'bg-gray-100 text-gray-700',
}

/** Solid hex per tone — used by the calendar so events never get an undefined colour. */
export const TONE_HEX: Record<StatusTone, string> = {
  success: '#10b981',
  warning: '#f59e0b',
  error: '#ef4444',
  info: '#6b7280',
  neutral: '#9ca3af',
}
