import { format } from 'date-fns'
import { es } from 'date-fns/locale'
import type { Appointment } from './supabase/types'

/**
 * The API denormalises the patient name onto each appointment, but it comes
 * back null when the relationship wasn't eagerly loaded (e.g. the row a POST
 * just created). Fall back to a clean label rather than render a raw UUID.
 */
export function patientLabel(appointment: Appointment): string {
  const name = appointment.patient_name
  return name && name.trim() ? name.trim() : 'Paciente'
}

/**
 * Format a date coming from the API, tolerating a missing or malformed value.
 *
 * date-fns throws RangeError on an invalid Date, so calling `format` directly
 * on an absent field takes down the whole screen. A missing date is a data
 * problem worth showing as a dash — never worth a blank page.
 */
export function formatDateSafe(
  value: string | null | undefined,
  pattern: string,
  fallback = '—'
): string {
  if (!value) return fallback
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return fallback
  return format(date, pattern, { locale: es })
}

/** Milliseconds since epoch, or null when the value can't be parsed. */
export function timestampSafe(value: string | null | undefined): number | null {
  if (!value) return null
  const ms = new Date(value).getTime()
  return Number.isNaN(ms) ? null : ms
}

/**
 * Sort comparator by appointment start. Rows with an unusable date sink to the
 * end instead of scrambling the order around a NaN comparison.
 */
export function byStartTime(a: Appointment, b: Appointment): number {
  const left = timestampSafe(a.start_datetime)
  const right = timestampSafe(b.start_datetime)
  if (left === null) return right === null ? 0 : 1
  if (right === null) return -1
  return left - right
}
