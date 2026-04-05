import { createBrowserSupabaseClient } from './supabase/browser'
import type { Appointment, Patient, Office } from './supabase/types'

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
    const headers: HeadersInit = {
      'Content-Type': 'application/json',
      ...options.headers,
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

  // Appointments
  async getAppointments(
    office_id: string,
    filters?: { start_date?: string; end_date?: string; status?: string }
  ): Promise<ApiResponse<Appointment[]>> {
    const params = new URLSearchParams()
    params.append('office_id', office_id)

    if (filters?.start_date) params.append('start_date', filters.start_date)
    if (filters?.end_date) params.append('end_date', filters.end_date)
    if (filters?.status) params.append('status', filters.status)

    return this.fetch<Appointment[]>(`/api/appointments?${params}`, {
      method: 'GET',
    })
  }

  async getAppointmentsToday(office_id: string): Promise<ApiResponse<Appointment[]>> {
    return this.fetch<Appointment[]>(`/api/appointments/today?office_id=${office_id}`, {
      method: 'GET',
    })
  }

  async getAppointment(appointment_id: string): Promise<ApiResponse<Appointment>> {
    return this.fetch<Appointment>(`/api/appointments/${appointment_id}`, {
      method: 'GET',
    })
  }

  async createAppointment(data: Partial<Appointment> & { office_id: string }): Promise<ApiResponse<Appointment>> {
    return this.fetch<Appointment>('/api/appointments', {
      method: 'POST',
      body: JSON.stringify(data),
    })
  }

  async updateAppointment(appointment_id: string, data: Partial<Appointment>): Promise<ApiResponse<Appointment>> {
    return this.fetch<Appointment>(`/api/appointments/${appointment_id}`, {
      method: 'PUT',
      body: JSON.stringify(data),
    })
  }

  async deleteAppointment(appointment_id: string): Promise<ApiResponse<{ success: boolean }>> {
    return this.fetch<{ success: boolean }>(`/api/appointments/${appointment_id}`, {
      method: 'DELETE',
    })
  }

  async moveBlock(
    appointment_id: string,
    new_date_time: string,
    duration_minutes?: number
  ): Promise<ApiResponse<Appointment>> {
    return this.fetch<Appointment>(`/api/appointments/${appointment_id}/move`, {
      method: 'POST',
      body: JSON.stringify({ new_date_time, duration_minutes }),
    })
  }

  // Patients
  async getPatients(office_id: string, search?: string): Promise<ApiResponse<Patient[]>> {
    const params = new URLSearchParams({ office_id })
    if (search) params.append('search', search)

    return this.fetch<Patient[]>(`/api/patients?${params}`, {
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

  // Office
  async getOffice(office_id: string): Promise<ApiResponse<Office>> {
    return this.fetch<Office>(`/api/office/${office_id}`, {
      method: 'GET',
    })
  }

  async updateOffice(office_id: string, data: Partial<Office>): Promise<ApiResponse<Office>> {
    return this.fetch<Office>(`/api/office/${office_id}`, {
      method: 'PUT',
      body: JSON.stringify(data),
    })
  }

  async getAvailability(office_id: string, date?: string): Promise<ApiResponse<Record<string, boolean>>> {
    const params = new URLSearchParams({ office_id })
    if (date) params.append('date', date)

    return this.fetch<Record<string, boolean>>(`/api/office/${office_id}/availability?${params}`, {
      method: 'GET',
    })
  }

  async updateSchedules(
    office_id: string,
    schedules: Record<string, unknown>
  ): Promise<ApiResponse<Office>> {
    return this.fetch<Office>(`/api/office/${office_id}`, {
      method: 'PUT',
      body: JSON.stringify({ schedules }),
    })
  }

  // Bot Control
  async pauseBot(office_id: string): Promise<ApiResponse<{ bot_status: string }>> {
    return this.fetch<{ bot_status: string }>(`/api/office/${office_id}/pause`, {
      method: 'POST',
    })
  }

  async resumeBot(office_id: string): Promise<ApiResponse<{ bot_status: string }>> {
    return this.fetch<{ bot_status: string }>(`/api/office/${office_id}/resume`, {
      method: 'POST',
    })
  }

  // Analytics
  async getStats(office_id: string, period?: 'day' | 'week' | 'month'): Promise<ApiResponse<{
    total_appointments: number
    confirmed_appointments: number
    pending_appointments: number
    no_show_appointments: number
    total_patients: number
  }>> {
    const params = new URLSearchParams({ office_id })
    if (period) params.append('period', period)

    return this.fetch(`/api/office/${office_id}/stats?${params}`, {
      method: 'GET',
    })
  }

  // Google Calendar Integration
  async getGoogleCalendarAuthUrl(office_id: string): Promise<ApiResponse<{ auth_url: string }>> {
    return this.fetch<{ auth_url: string }>(`/api/integrations/google-calendar/auth-url`, {
      method: 'POST',
      body: JSON.stringify({ office_id }),
    })
  }

  async syncGoogleCalendar(office_id: string, code: string): Promise<ApiResponse<{ success: boolean }>> {
    return this.fetch<{ success: boolean }>(`/api/integrations/google-calendar/sync`, {
      method: 'POST',
      body: JSON.stringify({ office_id, code }),
    })
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
