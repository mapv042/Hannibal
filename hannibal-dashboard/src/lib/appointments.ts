import type { Appointment } from './supabase/types'

/**
 * Appointments may arrive with a denormalised patient name from the API
 * (e.g. `patient_name` or a nested `patient` relation). The base type only
 * guarantees `patient_id`, so we read the name defensively and never render a
 * raw UUID to the doctor.
 *
 * The moment the backend includes the name, it shows automatically. Until
 * then the doctor sees a clean fallback instead of an identifier.
 */
type AppointmentWithPatient = Appointment & {
  patient_name?: string | null
  patient?: { name?: string | null } | null
}

export function patientLabel(appointment: Appointment): string {
  const a = appointment as AppointmentWithPatient
  const name = a.patient_name ?? a.patient?.name
  return name && name.trim() ? name.trim() : 'Paciente'
}
