export type Office = {
  id: string
  user_id: string
  name: string
  specialty: string | null
  whatsapp_phone: string | null
  owner_phone: string | null
  city: string | null
  state: string | null
  address: string | null
  assistant_tone: string
  assistant_name: string
  custom_prompt: string | null
  welcome_message: string | null
  new_patient_duration_min: number
  returning_patient_duration_min: number
  new_patient_cost: string | null
  returning_patient_cost: string | null
  is_active: boolean
  onboarding_completed: boolean
  notify_new_appointment: boolean
  notify_cancellation: boolean
  notify_new_patient: boolean
  notify_unconfirmed: boolean
  notify_arrival: boolean
  google_calendar_token: Record<string, unknown> | null
  plan: string
  created_at: string
  updated_at: string | null
}

/**
 * Mirrors the backend's AppointmentResponse (scheduling/schemas.py) field for
 * field. These types used to describe rows read straight from Supabase; the
 * dashboard now goes through the API, so the API's shape is the contract.
 */
export type Appointment = {
  id: string
  office_id: string
  patient_id: string
  /** Denormalised by the API; null when the relationship wasn't loaded. */
  patient_name: string | null
  start_datetime: string
  end_datetime: string
  duration_minutes: number
  type: string
  consultation_reason: string | null
  status: 'scheduled' | 'confirmed' | 'cancelled' | 'completed' | 'no_show'
  post_consultation_notes: string | null
  instructions: string | null
  cancelled_by: string | null
  cancellation_reason: string | null
  reminder_day_before_sent: boolean
  reminder_4h_sent: boolean
  reminder_1h_sent: boolean
  follow_up_sent: boolean
  /** Waiting room: null until the patient answers the arrival check-in. */
  arrival_status: 'on_the_way' | 'arrived' | 'no_answer' | null
  arrival_reported_at: string | null
  arrival_eta_minutes: number | null
  google_event_id: string | null
  created_at: string
  updated_at: string | null
}

/** Mirrors the backend's PatientResponse (patients/schemas.py). */
export type Patient = {
  id: string
  office_id: string
  name: string | null
  phone: string
  whatsapp_id: string
  email: string | null
  birth_date: string | null
  main_reason: string | null
  how_found_us: string | null
  internal_notes: string | null
  is_active: boolean
  first_appointment_at: string | null
  last_appointment_at: string | null
  total_appointments: number
  created_at: string
}

export type Doctor = {
  id: string
  email: string
  name: string
  specialty: string
  city: string
  created_at: string
  updated_at: string
}

export type AvailabilitySchedule = {
  id: string
  office_id: string
  day_of_week: number
  start_time: string
  end_time: string
  appointment_duration_min: number
  buffer_minutes: number
  is_active: boolean
}
