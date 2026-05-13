export type Office = {
  id: string
  user_id: string
  name: string
  specialty: string | null
  whatsapp_phone: string | null
  owner_phone: string | null
  city: string | null
  address: string | null
  assistant_tone: string
  assistant_name: string
  custom_prompt: string | null
  is_active: boolean
  onboarding_completed: boolean
  google_calendar_token: Record<string, unknown> | null
  plan: string
  created_at: string
  updated_at: string | null
}

export type Appointment = {
  id: string
  office_id: string
  patient_id: string
  date_time: string
  duration_minutes: number
  consultation_type: string
  status: 'confirmed' | 'pending' | 'blocked' | 'no_show' | 'cancelled'
  notes: string
  created_at: string
  updated_at: string
}

export type Patient = {
  id: string
  office_id: string
  name: string
  whatsapp_number: string
  email: string
  total_consultations: number
  last_consultation_at: string | null
  notes: string
  created_at: string
  updated_at: string
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
