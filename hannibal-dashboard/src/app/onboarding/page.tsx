'use client'

import React, { useState, useEffect, useCallback, useMemo } from 'react'
import { useRouter, useSearchParams } from 'next/navigation'
import { createBrowserSupabaseClient } from '@/lib/supabase'
import { useApi, type ReminderRule } from '@/lib/api'
import type { AvailabilitySchedule, Office } from '@/lib/supabase'

import {
  OnboardingWizard,
  type OnboardingData,
} from '@/components/onboarding/OnboardingWizard'
import { rulesFromReminderToggles } from '@/components/onboarding/StepSchedule'
import {
  consultationPayload,
  durationsPayload,
  formDataFromOffice,
  officeInfoPayload,
  personalizePayload,
  schedulesPayload,
} from '@/lib/officeForm'

export default function OnboardingPage() {
  const [office, setOffice] = useState<Office | null>(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [gcalConnected, setGcalConnected] = useState(false)
  const [reminderRules, setReminderRules] = useState<ReminderRule[] | null>(null)
  const [schedules, setSchedules] = useState<AvailabilitySchedule[] | null>(null)

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
            // Coming back from the Google OAuth flow with onboarding already
            // finished: hand the notice to Settings rather than dropping it.
            // The backend falls back to /onboarding when it cannot resolve the
            // state nonce, so swallowing it here makes a real failure look
            // exactly like a silent success.
            router.push(
              gcalParam === 'success' || gcalParam === 'error'
                ? `/dashboard/settings?gcal=${gcalParam}`
                : '/dashboard'
            )
            return
          }

          setOffice(existingOffice)
          if (existingOffice.google_calendar_connected) {
            setGcalConnected(true)
          }

          // Pre-fill reminders and hours already saved in an earlier visit.
          const [rulesRes, schedulesRes] = await Promise.all([
            api.getReminderRules(existingOffice.id),
            api.getAvailabilitySchedules(),
          ])
          if (rulesRes.success && rulesRes.data) {
            setReminderRules(rulesRes.data)
          }
          if (schedulesRes.success && schedulesRes.data) {
            setSchedules(schedulesRes.data)
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
  const initialData = useMemo<Partial<OnboardingData> | undefined>(
    () => (office ? formDataFromOffice(office, reminderRules, schedules) : undefined),
    [office, reminderRules, schedules]
  )

  const handleSubmitOfficeInfo = useCallback(
    async ({ officeInfo }: OnboardingData) => {
      setSaving(true)
      setError('')
      try {
        const payload = officeInfoPayload(officeInfo)

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
        const res = await api.upsertAvailabilitySchedules(schedulesPayload(schedule))
        if (!res.success) throw new Error(res.error)

        const durationRes = await api.updateOffice(office.id, durationsPayload(schedule))
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
        const res = await api.updateOffice(office.id, consultationPayload(consultation))
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
    async ({ personalize }: OnboardingData) => {
      if (!office) return false
      setSaving(true)
      setError('')
      try {
        const res = await api.updateOffice(office.id, personalizePayload(personalize))
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
    setError('')
    try {
      const res = await api.updateOffice(office.id, {
        onboarding_completed: true,
      } as Partial<Office>)
      // The backend refuses to finish an under-configured office and names what
      // is missing. Navigating anyway would bounce the doctor straight back here
      // from DashboardShell with no explanation.
      if (!res.success) {
        setError(res.error || 'No pudimos terminar la configuración.')
        return
      }
      router.push('/dashboard')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'No pudimos terminar la configuración.')
    } finally {
      setSaving(false)
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
      officeId={office?.id ?? null}
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
