'use client'

import React, { useState, useEffect, useCallback, useMemo } from 'react'
import { useRouter, useSearchParams } from 'next/navigation'
import { createBrowserSupabaseClient } from '@/lib/supabase'
import { useApi, type ReminderRule } from '@/lib/api'
import type { Office } from '@/lib/supabase'

import {
  OnboardingWizard,
  buildInitialScheduleDays,
  type OnboardingData,
} from '@/components/onboarding/OnboardingWizard'
import type { ConsultationData } from '@/components/onboarding/StepConsultationDetails'
import type { PersonalizeData } from '@/components/onboarding/StepPersonalize'
import {
  reminderTogglesFromRules,
  rulesFromReminderToggles,
} from '@/components/onboarding/StepSchedule'

function buildCustomPrompt(
  consultation: ConsultationData,
  personalize: PersonalizeData
): string {
  const parts: string[] = []

  // Insurance info goes in custom_prompt (pricing is now in dedicated columns)
  if (consultation.acceptsInsurance) {
    if (consultation.acceptsInsurance === 'Si' || consultation.acceptsInsurance === 'Algunos') {
      parts.push(`SEGUROS MEDICOS:`)
      parts.push(`- Seguros aceptados: ${consultation.insuranceDetails || 'Preguntar al consultorio'}`)
    } else if (consultation.acceptsInsurance === 'No') {
      parts.push('SEGUROS MEDICOS:')
      parts.push('- No se aceptan seguros medicos')
    }
    parts.push('')
  }

  if (personalize.emergencySymptoms.trim()) {
    parts.push('SINTOMAS DE EMERGENCIA:')
    parts.push(personalize.emergencySymptoms.trim())
  }

  return parts.join('\n')
}

export default function OnboardingPage() {
  const [office, setOffice] = useState<Office | null>(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [gcalConnected, setGcalConnected] = useState(false)
  const [reminderRules, setReminderRules] = useState<ReminderRule[] | null>(null)

  const router = useRouter()
  const searchParams = useSearchParams()
  const supabase = createBrowserSupabaseClient()
  const api = useApi()

  // Land directly on the Google Calendar step when returning from OAuth.
  const gcalParam = searchParams.get('gcal')
  const initialStep = gcalParam === 'success' || gcalParam === 'error' ? 6 : 0

  // Load office on mount
  useEffect(() => {
    const loadOffice = async () => {
      try {
        const { data: { user } } = await supabase.auth.getUser()
        if (!user) {
          router.push('/login')
          return
        }

        const response = await api.listOffices()
        if (response.success && response.data && response.data.length > 0) {
          const existingOffice = response.data[0]

          if (existingOffice.onboarding_completed) {
            router.push('/dashboard')
            return
          }

          setOffice(existingOffice)
          if (existingOffice.google_calendar_token) {
            setGcalConnected(true)
          }

          // Load the office's reminder configuration to pre-fill the toggles.
          const rulesRes = await api.getReminderRules(existingOffice.id)
          if (rulesRes.success && rulesRes.data) {
            setReminderRules(rulesRes.data)
          }
        }
        // If no office exists, it will be created after step 1
      } catch (err) {
        console.error('Error loading office:', err)
      } finally {
        setLoading(false)
      }
    }

    loadOffice()

    if (gcalParam === 'success') {
      setGcalConnected(true)
    } else if (gcalParam === 'error') {
      setError('Error al conectar Google Calendar. Intenta de nuevo.')
    }
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  // Pre-fill the wizard from the loaded office (computed once loading finishes).
  const initialData = useMemo<Partial<OnboardingData> | undefined>(() => {
    if (!office) return undefined
    return {
      officeInfo: {
        officeName: office.name || '',
        specialty: office.specialty || '',
        city: office.city || '',
        state: office.state || '',
        address: office.address || '',
        ownerPhone: office.owner_phone || '',
      },
      schedule: {
        days: buildInitialScheduleDays(),
        appointmentDuration: Math.max(
          office.new_patient_duration_min || 30,
          office.returning_patient_duration_min || 30
        ),
        newPatientDuration: office.new_patient_duration_min || 30,
        returningPatientDuration: office.returning_patient_duration_min || 30,
        bufferMinutes: 10,
        reminders: reminderTogglesFromRules(reminderRules ?? undefined),
      },
      consultation: {
        newPatientCost: office.new_patient_cost || '',
        returningPatientCost: office.returning_patient_cost || '',
        acceptsInsurance: '',
        insuranceDetails: '',
      },
      personalize:
        office.assistant_name && office.assistant_name !== 'Assistant'
          ? {
              assistantName: office.assistant_name,
              assistantTone: office.assistant_tone as 'formal' | 'informal',
              emergencySymptoms: '',
              welcomeMessage: office.welcome_message || '',
            }
          : undefined,
    }
  }, [office, reminderRules])

  const handleSubmitOfficeInfo = useCallback(
    async ({ officeInfo }: OnboardingData) => {
      setSaving(true)
      setError('')
      try {
        const payload = {
          name: officeInfo.officeName,
          specialty: officeInfo.specialty || undefined,
          city: officeInfo.city || undefined,
          state: officeInfo.state || undefined,
          address: officeInfo.address || undefined,
          owner_phone: officeInfo.ownerPhone || undefined,
        }

        const res = office
          ? await api.updateOffice(office.id, payload)
          : await api.createOffice(payload)
        if (!res.success) throw new Error(res.error)
        setOffice(res.data!)
        return true
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Error al guardar')
        return false
      } finally {
        setSaving(false)
      }
    },
    [office, api]
  )

  const handleSubmitSchedule = useCallback(
    async ({ schedule }: OnboardingData) => {
      if (!office) return false
      setSaving(true)
      setError('')
      try {
        const schedules = schedule.days
          .filter((d) => d.enabled)
          .flatMap((d) =>
            d.blocks.map((block) => ({
              day_of_week: d.dayOfWeek,
              start_time: block.startTime,
              end_time: block.endTime,
              appointment_duration_min: schedule.appointmentDuration,
              buffer_minutes: schedule.bufferMinutes,
            }))
          )

        const res = await api.upsertAvailabilitySchedules(schedules)
        if (!res.success) throw new Error(res.error)

        const durationRes = await api.updateOffice(office.id, {
          new_patient_duration_min: schedule.newPatientDuration,
          returning_patient_duration_min: schedule.returningPatientDuration,
        })
        if (durationRes.success && durationRes.data) {
          setOffice(durationRes.data)
        }

        // Persist the reminder configuration chosen via the checkboxes.
        const rules: ReminderRule[] = rulesFromReminderToggles(schedule.reminders)
        const rulesRes = await api.updateReminderRules(office.id, rules)
        if (rulesRes.success && rulesRes.data) {
          setReminderRules(rulesRes.data)
        }
        return true
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Error al guardar')
        return false
      } finally {
        setSaving(false)
      }
    },
    [office, api]
  )

  const handleSubmitConsultation = useCallback(
    async ({ consultation }: OnboardingData) => {
      if (!office) return false
      setSaving(true)
      setError('')
      try {
        const res = await api.updateOffice(office.id, {
          new_patient_cost: consultation.newPatientCost || undefined,
          returning_patient_cost: consultation.returningPatientCost || undefined,
        })
        if (!res.success) throw new Error(res.error)
        setOffice(res.data!)
        return true
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Error al guardar')
        return false
      } finally {
        setSaving(false)
      }
    },
    [office, api]
  )

  const handleSubmitPersonalize = useCallback(
    async ({ consultation, personalize }: OnboardingData) => {
      if (!office) return false
      setSaving(true)
      setError('')
      try {
        const customPrompt = buildCustomPrompt(consultation, personalize)
        const res = await api.updateOffice(office.id, {
          assistant_name: personalize.assistantName || 'Asistente',
          assistant_tone: personalize.assistantTone,
          custom_prompt: customPrompt || undefined,
          welcome_message: personalize.welcomeMessage || undefined,
        })
        if (!res.success) throw new Error(res.error)
        setOffice(res.data!)
        return true
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Error al guardar')
        return false
      } finally {
        setSaving(false)
      }
    },
    [office, api]
  )

  const handleFinish = useCallback(async () => {
    if (!office) return
    setSaving(true)
    try {
      await api.updateOffice(office.id, { onboarding_completed: true } as Partial<Office>)
      router.push('/dashboard')
    } catch (err) {
      console.error('Error finishing onboarding:', err)
      router.push('/dashboard')
    }
  }, [office, api, router])

  if (loading) {
    return (
      <div className="text-center py-20">
        <div className="w-10 h-10 rounded-full border-4 border-primary-200 border-t-primary-600 animate-spin mx-auto mb-4" />
        <p className="text-gray-600">Cargando...</p>
      </div>
    )
  }

  return (
    <OnboardingWizard
      initialStep={initialStep}
      initialData={initialData}
      gcalConnected={gcalConnected}
      saving={saving}
      error={error}
      onSubmitOfficeInfo={handleSubmitOfficeInfo}
      onSubmitSchedule={handleSubmitSchedule}
      onSubmitConsultation={handleSubmitConsultation}
      onSubmitPersonalize={handleSubmitPersonalize}
      onFinish={handleFinish}
    />
  )
}
