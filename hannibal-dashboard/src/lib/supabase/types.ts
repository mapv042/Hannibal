export type Office = {
  id: string
  doctor_id: string
  assistant_name: string
  tone: 'formal' | 'informal'
  custom_prompt: string
  schedules: Record<string, unknown>
  bot_status: 'active' | 'paused' | 'inactive'
  whatsapp_number: string
  created_at: string
  updated_at: string
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
