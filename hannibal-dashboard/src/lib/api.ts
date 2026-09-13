import { createBrowserSupabaseClient } from './supabase/browser'
import type { Appointment, Patient, Office, AvailabilitySchedule } from './supabase/types'
import type { CatalogOption } from './constants/catalogs'

export interface ApiResponse<T> {
  success: boolean
  data?: T
  error?: string
  message?: string
}

export interface PaginatedResponse<T> {
  items: T[]
  total: number
  page: number
  per_page: number
}

export type StatsPeriod = 'week' | 'month' | 'quarter'

export interface PeriodStats {
  total_appointments: number
  confirmed_appointments: number
  attended_appointments: number
  no_show_appointments: number
  cancelled_appointments: number
  total_patients: number
  /** Null when the period had no appointments to rate. */
  confirmation_rate: number | null
  no_show_rate: number | null
}

export interface OfficeStats extends PeriodStats {
  period: StatsPeriod
  period_days: number
  previous: PeriodStats
  /** Change in volume vs. the previous period; null when it had none. */
  change_pct: number | null
}

export interface ReminderRule {
  reminder_type: string
  offset_minutes: number
  enabled: boolean
}

export class ApiClient {
  private baseUrl: string
  private supabase: ReturnType<typeof createBrowserSupabaseClient> | null = null

  constructor(baseUrl: string = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000') {
    this.baseUrl = baseUrl
  }

  private async getAuthToken(): Promise<string | null> {
    try {
      if (!this.supabase) {
        this.supabase = createBrowserSupabaseClient()
      }
      const {
        data: { session },
      } = await this.supabase.auth.getSession()
      return session?.access_token || null
    } catch {
      return null
    }
  }

  private async fetch<T>(
    endpoint: string,
    options: RequestInit = {}
  ): Promise<ApiResponse<T>> {
    const token = await this.getAuthToken()
    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
    }

    if (token) {
      headers['Authorization'] = `Bearer ${token}`
    }

    try {
      const response = await fetch(`${this.baseUrl}${endpoint}`, {
        ...options,
        headers,
      })

      if (!response.ok) {
        const error = await response.json()
        return {
          success: false,
          error: error.detail || error.message || 'Request failed',
        }
      }

      const data = await response.json()
      return {
        success: true,
        data,
      }
    } catch (error) {
      return {
        success: false,
        error: error instanceof Error ? error.message : 'Unknown error',
      }
    }
  }

  // Offices
  async createOffice(data: {
    doctor_first_name?: string
    doctor_last_name?: string
    secondary_owner_phone?: string
    name: string
    specialty?: string
    city?: string
    state?: string
    address?: string
    owner_phone?: string
  }): Promise<ApiResponse<Office>> {
    return this.fetch<Office>('/api/offices', {
      method: 'POST',
      body: JSON.stringify(data),
    })
  }

  async listOffices(): Promise<ApiResponse<Office[]>> {
    return this.fetch<Office[]>('/api/offices', {
      method: 'GET',
    })
  }

  async getOffice(office_id: string): Promise<ApiResponse<Office>> {
    return this.fetch<Office>(`/api/offices/${office_id}`, {
      method: 'GET',
    })
  }

  async updateOffice(office_id: string, data: Partial<Office>): Promise<ApiResponse<Office>> {
    return this.fetch<Office>(`/api/offices/${office_id}`, {
      method: 'PUT',
      body: JSON.stringify(data),
    })
  }

  // Onboarding catalogues. Served by the backend so the options the doctor
  // picks from and the labels the assistant says to patients stay identical.
  async getSpecialties(): Promise<ApiResponse<{ specialties: CatalogOption[] }>> {
    return this.fetch<{ specialties: CatalogOption[] }>('/api/catalogs/specialties', {
      method: 'GET',
    })
  }

  async getInsurers(): Promise<ApiResponse<{ insurers: CatalogOption[] }>> {
    return this.fetch<{ insurers: CatalogOption[] }>('/api/catalogs/insurers', {
      method: 'GET',
    })
  }

  async getIntakeQuestions(): Promise<ApiResponse<{ questions: CatalogOption[] }>> {
    return this.fetch<{ questions: CatalogOption[] }>('/api/catalogs/intake-questions', {
      method: 'GET',
    })
  }

  async getCatalogsBySpecialty(
    specialty: string
  ): Promise<ApiResponse<{ services: string[]; emergency_symptoms: string[] }>> {
    return this.fetch<{ services: string[]; emergency_symptoms: string[] }>(
      `/api/catalogs/by-specialty?specialty=${encodeURIComponent(specialty)}`,
      { method: 'GET' }
    )
  }

  // Reminder rules (per office)
  async getReminderRules(office_id: string): Promise<ApiResponse<ReminderRule[]>> {
    return this.fetch<ReminderRule[]>(`/api/offices/${office_id}/reminder-rules`, {
      method: 'GET',
    })
  }

  async updateReminderRules(
    office_id: string,
    rules: ReminderRule[]
  ): Promise<ApiResponse<ReminderRule[]>> {
    return this.fetch<ReminderRule[]>(`/api/offices/${office_id}/reminder-rules`, {
      method: 'PUT',
      body: JSON.stringify({ rules }),
    })
  }

  // Appointments
  async getAppointments(
    _office_id: string,
    filters?: { start_date?: string; end_date?: string; status?: string }
  ): Promise<ApiResponse<Appointment[]>> {
    const params = new URLSearchParams()
    if (filters?.start_date) params.append('start_date', filters.start_date)
    if (filters?.end_date) params.append('end_date', filters.end_date)
    if (filters?.status) params.append('status', filters.status)

    const qs = params.toString()
    return this.fetch<Appointment[]>(`/api/scheduling/appointments${qs ? `?${qs}` : ''}`, {
      method: 'GET',
    })
  }

  async getAppointmentsToday(office_id: string): Promise<ApiResponse<Appointment[]>> {
    const today = new Date().toISOString().split('T')[0]
    const tomorrow = new Date(Date.now() + 86400000).toISOString().split('T')[0]
    return this.getAppointments(office_id, { start_date: today, end_date: tomorrow })
  }

  async getAppointment(appointment_id: string): Promise<ApiResponse<Appointment>> {
    return this.fetch<Appointment>(`/api/scheduling/appointments/${appointment_id}`, {
      method: 'GET',
    })
  }

  async createAppointment(data: Partial<Appointment> & { office_id: string }): Promise<ApiResponse<Appointment>> {
    return this.fetch<Appointment>('/api/scheduling/appointments', {
      method: 'POST',
      body: JSON.stringify(data),
    })
  }

  async updateAppointment(appointment_id: string, data: Partial<Appointment>): Promise<ApiResponse<Appointment>> {
    return this.fetch<Appointment>(`/api/scheduling/appointments/${appointment_id}`, {
      method: 'PUT',
      body: JSON.stringify(data),
    })
  }

  async deleteAppointment(appointment_id: string): Promise<ApiResponse<{ success: boolean }>> {
    return this.fetch<{ success: boolean }>(`/api/scheduling/appointments/${appointment_id}`, {
      method: 'DELETE',
    })
  }

  // Patients
  async getPatients(_office_id: string, search?: string): Promise<ApiResponse<Patient[]>> {
    const params = new URLSearchParams()
    if (search) params.append('search', search)

    const qs = params.toString()
    return this.fetch<Patient[]>(`/api/patients${qs ? `?${qs}` : ''}`, {
      method: 'GET',
    })
  }

  async getPatient(patient_id: string): Promise<ApiResponse<Patient>> {
    return this.fetch<Patient>(`/api/patients/${patient_id}`, {
      method: 'GET',
    })
  }

  async createPatient(data: Partial<Patient> & { office_id: string }): Promise<ApiResponse<Patient>> {
    return this.fetch<Patient>('/api/patients', {
      method: 'POST',
      body: JSON.stringify(data),
    })
  }

  async updatePatient(patient_id: string, data: Partial<Patient>): Promise<ApiResponse<Patient>> {
    return this.fetch<Patient>(`/api/patients/${patient_id}`, {
      method: 'PUT',
      body: JSON.stringify(data),
    })
  }

  // Availability Schedules
  async getAvailabilitySchedules(): Promise<ApiResponse<AvailabilitySchedule[]>> {
    return this.fetch<AvailabilitySchedule[]>('/api/scheduling/schedules', {
      method: 'GET',
    })
  }

  async upsertAvailabilitySchedules(
    schedules: Array<{
      day_of_week: number
      start_time: string
      end_time: string
      appointment_duration_min: number
      buffer_minutes: number
    }>
  ): Promise<ApiResponse<AvailabilitySchedule[]>> {
    return this.fetch<AvailabilitySchedule[]>('/api/scheduling/schedules', {
      method: 'PUT',
      body: JSON.stringify({ schedules }),
    })
  }

  // Availability
  async getAvailability(_office_id: string, date?: string): Promise<ApiResponse<Record<string, boolean>>> {
    const params = new URLSearchParams()
    if (date) params.append('date', date)

    const qs = params.toString()
    return this.fetch<Record<string, boolean>>(`/api/scheduling/availability${qs ? `?${qs}` : ''}`, {
      method: 'GET',
    })
  }

  // Bot Control
  async pauseBot(office_id: string): Promise<ApiResponse<{ bot_status: string }>> {
    return this.fetch<{ bot_status: string }>(`/api/offices/${office_id}/pause`, {
      method: 'POST',
    })
  }

  async resumeBot(office_id: string): Promise<ApiResponse<{ bot_status: string }>> {
    return this.fetch<{ bot_status: string }>(`/api/offices/${office_id}/resume`, {
      method: 'POST',
    })
  }

  // Analytics
  async getStats(
    office_id: string,
    period: StatsPeriod = 'month'
  ): Promise<ApiResponse<OfficeStats>> {
    return this.fetch<OfficeStats>(
      `/api/offices/${office_id}/stats?period=${period}`,
      { method: 'GET' }
    )
  }

  // WhatsApp Integration (Embedded Signup)
  async completeWhatsAppSignup(data: {
    office_id: string
    code: string
    phone_number_id: string
    waba_id: string
    mode?: 'coexistence' | 'dedicated' | 'new'
  }): Promise<ApiResponse<{ status: string; phone_number: string | null; verified_name: string | null }>> {
    return this.fetch('/api/auth/whatsapp/embedded-signup', {
      method: 'POST',
      body: JSON.stringify({ mode: 'coexistence', ...data }),
    })
  }

  async getWhatsAppStatus(office_id: string): Promise<ApiResponse<{
    active: boolean
    phone_number: string | null
    phone_number_id: string | null
    waba_id: string | null
    mode: string | null
  }>> {
    return this.fetch(`/api/auth/whatsapp/status/${office_id}`, {
      method: 'GET',
    })
  }

  // Google Calendar Integration
  /** `returnTo` names the page the OAuth callback sends the browser back to. */
  async getGoogleCalendarAuthUrl(
    returnTo: 'onboarding' | 'settings' = 'onboarding'
  ): Promise<ApiResponse<{ auth_url: string }>> {
    return this.fetch<{ auth_url: string }>(
      `/api/google-calendar/auth/url?return_to=${returnTo}`,
      { method: 'GET' }
    )
  }

  async disconnectGoogleCalendar(): Promise<ApiResponse<{ success: boolean }>> {
    return this.fetch<{ success: boolean }>('/api/google-calendar/disconnect', {
      method: 'POST',
    })
  }

  async checkGoogleCalendarConnected(): Promise<ApiResponse<{ connected: boolean }>> {
    const res = await this.listOffices()
    if (res.success && res.data && res.data.length > 0) {
      return {
        success: true,
        data: { connected: !!res.data[0].google_calendar_token },
      }
    }
    return { success: true, data: { connected: false } }
  }
}

// Singleton instance
let apiClient: ApiClient | null = null

export function getApiClient(): ApiClient {
  if (!apiClient) {
    apiClient = new ApiClient()
  }
  return apiClient
}

// Hook for use in client components
export function useApi(): ApiClient {
  return getApiClient()
}
