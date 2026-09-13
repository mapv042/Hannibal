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
import {
  reminderTogglesFromRules,
  rulesFromReminderToggles,
} from '@/components/onboarding/StepSchedule'
import {
  OTHER_SPECIALTY_ID,
  isCatalogSpecialty,
  type InsuranceChoice,
} from '@/lib/constants/catalogs'

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
    const knownSpecialty = isCatalogSpecialty(office.specialty)
    return {
      officeInfo: {
        doctorFirstName: office.doctor_first_name || '',
        doctorLastName: office.doctor_last_name || '',
        officeName: office.name || '',
        // A specialty outside the catalogue was stored as free text under
        // "Otra"; put it back in the right two fields.
        specialty: knownSpecialty ? office.specialty! : office.specialty ? OTHER_SPECIALTY_ID : '',
        specialtyOther: knownSpecialty ? '' : office.specialty || '',
        city: office.city || '',
        state: office.state || '',
        address: office.address || '',
        ownerPhone: office.owner_phone || '',
        secondaryOwnerPhone: office.secondary_owner_phone || '',
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
        services: (office.services || []).map((s) => ({
          name: s.name,
          price: s.price || '',
        })),
        acceptsInsurance: (office.accepts_insurance || '') as InsuranceChoice,
        insurances: office.insurances || [],
      },
      personalize:
        office.assistant_name && office.assistant_name !== 'Assistant'
          ? {
              assistantName: office.assistant_name,
              assistantTone: office.assistant_tone as 'formal' | 'informal',
              assistantGender: office.assistant_gender || 'femenino',
              emergencySymptoms: office.emergency_symptoms || [],
              intakeQuestions: office.intake_questions?.preset || [],
              intakeCustom: office.intake_questions?.custom || '',
              notifyNewAppointment: office.notify_new_appointment,
              notifyCancellation: office.notify_cancellation,
              notifyNewPatient: office.notify_new_patient,
              notifyUnconfirmed: office.notify_unconfirmed,
              notifyArrival: office.notify_arrival,
            }
          : undefined,
    }
  }, [office, reminderRules])

  const handleSubmitOfficeInfo = useCallback(
    async ({ officeInfo }: OnboardingData) => {
      setSaving(true)
      setError('')
      try {
        // "Otra" stores what the doctor typed; anything else stores the id.
        const specialty =
          officeInfo.specialty === OTHER_SPECIALTY_ID
            ? officeInfo.specialtyOther.trim()
            : officeInfo.specialty

        const payload = {
          name: officeInfo.officeName,
          doctor_first_name: officeInfo.doctorFirstName || undefined,
          doctor_last_name: officeInfo.doctorLastName || undefined,
          specialty: specialty || undefined,
          city: officeInfo.city || undefined,
          state: officeInfo.state || undefined,
          address: officeInfo.address || undefined,
          owner_phone: officeInfo.ownerPhone || undefined,
          // Empty string clears a previously saved second number.
          secondary_owner_phone: officeInfo.secondaryOwnerPhone.trim(),
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
        const services = consultation.services.filter((s) => s.name.trim())
        // The two generic consultations keep feeding the prompt's PACIENTE
        // ACTUAL block, which quotes the price for this patient's visit type.
        const priceOf = (name: string) =>
          services.find((s) => s.name === name)?.price || undefined

        const res = await api.updateOffice(office.id, {
          services,
          accepts_insurance: consultation.acceptsInsurance || undefined,
          insurances: consultation.insurances,
          new_patient_cost: priceOf('Primera consulta'),
          returning_patient_cost: priceOf('Consulta subsecuente'),
        } as Partial<Office>)
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
        const res = await api.updateOffice(office.id, {
          assistant_name: personalize.assistantName,
          assistant_tone: personalize.assistantTone,
          assistant_gender: personalize.assistantGender,
          emergency_symptoms: personalize.emergencySymptoms.filter((s) => s.trim()),
          intake_questions: {
            preset: personalize.intakeQuestions,
            custom: personalize.intakeCustom.trim() || null,
          },
          notify_new_appointment: personalize.notifyNewAppointment,
          notify_cancellation: personalize.notifyCancellation,
          notify_new_patient: personalize.notifyNewPatient,
          notify_unconfirmed: personalize.notifyUnconfirmed,
          notify_arrival: personalize.notifyArrival,
        } as Partial<Office>)
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
