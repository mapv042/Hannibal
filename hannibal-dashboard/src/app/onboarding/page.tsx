'use client'

import React, { useState, useEffect, useCallback } from 'react'
import { useRouter, useSearchParams } from 'next/navigation'
import { createBrowserSupabaseClient } from '@/lib/supabase'
import { useApi } from '@/lib/api'
import type { Office } from '@/lib/supabase'

import { ProgressBar } from '@/components/onboarding/ProgressBar'
import { StepWelcome } from '@/components/onboarding/StepWelcome'
import { StepOfficeInfo, type OfficeInfoData } from '@/components/onboarding/StepOfficeInfo'
import { StepSchedule, type ScheduleData, type ScheduleDay } from '@/components/onboarding/StepSchedule'
import { StepConsultationDetails, type ConsultationData } from '@/components/onboarding/StepConsultationDetails'
import { StepPersonalize, type PersonalizeData } from '@/components/onboarding/StepPersonalize'
import { StepConnectWhatsApp } from '@/components/onboarding/StepConnectWhatsApp'
import { StepConnectCalendar } from '@/components/onboarding/StepConnectCalendar'
import { StepDone } from '@/components/onboarding/StepDone'
import {
  PreviewPane,
  SchedulePreview,
  ConsultationPreview,
  AssistantPreview,
} from '@/components/onboarding/PreviewPane'

const TOTAL_STEPS = 7 // excluding welcome (step 0)

const STEP_TITLES: Record<number, string> = {
  1: 'Tu consultorio',
  2: 'Horarios',
  3: 'Costos',
  4: 'Asistente',
  5: 'WhatsApp',
  6: 'Google Calendar',
}

function buildInitialScheduleDays(): ScheduleDay[] {
  // 0=Sun through 6=Sat, Mon-Fri enabled by default
  return [0, 1, 2, 3, 4, 5, 6].map((dow) => ({
    dayOfWeek: dow,
    enabled: dow >= 1 && dow <= 5, // Mon-Fri
    blocks: dow >= 1 && dow <= 5
      ? [{ startTime: '09:00', endTime: '17:00' }]
      : [],
  }))
}

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
  const [currentStep, setCurrentStep] = useState(0)
  const [office, setOffice] = useState<Office | null>(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  const [officeInfo, setOfficeInfo] = useState<OfficeInfoData>({
    officeName: '',
    specialty: '',
    city: '',
    state: '',
    address: '',
    ownerPhone: '',
  })

  const [schedule, setSchedule] = useState<ScheduleData>({
    days: buildInitialScheduleDays(),
    appointmentDuration: 30,
    newPatientDuration: 30,
    returningPatientDuration: 30,
    bufferMinutes: 10,
  })

  const [consultation, setConsultation] = useState<ConsultationData>({
    newPatientCost: '',
    returningPatientCost: '',
    acceptsInsurance: '',
    insuranceDetails: '',
  })

  const [personalize, setPersonalize] = useState<PersonalizeData>({
    assistantName: '',
    assistantTone: 'formal',
    emergencySymptoms: '',
    welcomeMessage: '',
  })

  const [gcalConnected, setGcalConnected] = useState(false)

  const router = useRouter()
  const searchParams = useSearchParams()
  const supabase = createBrowserSupabaseClient()
  const api = useApi()

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
          // Check if Google Calendar is already connected
          if (existingOffice.google_calendar_token) {
            setGcalConnected(true)
          }
          // Pre-fill with existing data
          setOfficeInfo({
            officeName: existingOffice.name || '',
            specialty: existingOffice.specialty || '',
            city: existingOffice.city || '',
            state: existingOffice.state || '',
            address: existingOffice.address || '',
            ownerPhone: existingOffice.owner_phone || '',
          })
          setSchedule((prev) => ({
            ...prev,
            newPatientDuration: existingOffice.new_patient_duration_min || 30,
            returningPatientDuration: existingOffice.returning_patient_duration_min || 30,
            appointmentDuration: Math.max(
              existingOffice.new_patient_duration_min || 30,
              existingOffice.returning_patient_duration_min || 30
            ),
          }))
          setConsultation((prev) => ({
            ...prev,
            newPatientCost: existingOffice.new_patient_cost || '',
            returningPatientCost: existingOffice.returning_patient_cost || '',
          }))
          if (existingOffice.assistant_name && existingOffice.assistant_name !== 'Assistant') {
            setPersonalize((prev) => ({
              ...prev,
              assistantName: existingOffice.assistant_name,
              assistantTone: existingOffice.assistant_tone as 'formal' | 'informal',
              welcomeMessage: existingOffice.welcome_message || '',
            }))
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

    // Handle Google Calendar OAuth callback
    const gcalParam = searchParams.get('gcal')
    if (gcalParam === 'success') {
      setGcalConnected(true)
      setCurrentStep(6)
    } else if (gcalParam === 'error') {
      setCurrentStep(6)
      setError('Error al conectar Google Calendar. Intenta de nuevo.')
    }
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  const handleSaveOfficeInfo = useCallback(async () => {
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

      if (office) {
        const res = await api.updateOffice(office.id, payload)
        if (!res.success) throw new Error(res.error)
        setOffice(res.data!)
      } else {
        const res = await api.createOffice(payload)
        if (!res.success) throw new Error(res.error)
        setOffice(res.data!)
      }
      setCurrentStep(2)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Error al guardar')
    } finally {
      setSaving(false)
    }
  }, [office, officeInfo, api])

  const handleSaveSchedule = useCallback(async () => {
    if (!office) return
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

      // Save patient-specific durations to Office
      const durationRes = await api.updateOffice(office.id, {
        new_patient_duration_min: schedule.newPatientDuration,
        returning_patient_duration_min: schedule.returningPatientDuration,
      })
      if (durationRes.success && durationRes.data) {
        setOffice(durationRes.data)
      }

      setCurrentStep(3)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Error al guardar')
    } finally {
      setSaving(false)
    }
  }, [office, schedule, api])

  const handleSaveConsultation = useCallback(async () => {
    if (!office) return
    setSaving(true)
    setError('')
    try {
      const res = await api.updateOffice(office.id, {
        new_patient_cost: consultation.newPatientCost || undefined,
        returning_patient_cost: consultation.returningPatientCost || undefined,
      })
      if (!res.success) throw new Error(res.error)
      setOffice(res.data!)
      setCurrentStep(4)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Error al guardar')
    } finally {
      setSaving(false)
    }
  }, [office, consultation, api])

  const handleSavePersonalize = useCallback(async () => {
    if (!office) return
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
      setCurrentStep(5)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Error al guardar')
    } finally {
      setSaving(false)
    }
  }, [office, consultation, personalize, api])

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

  const usesPreview = currentStep === 2 || currentStep === 3 || currentStep === 4

  return (
    <div className={usesPreview ? 'w-full' : 'max-w-2xl mx-auto'}>
      {/* Progress bar (hidden on welcome and done) */}
      {currentStep > 0 && currentStep < TOTAL_STEPS && (
        <div className="max-w-2xl mx-auto">
          <ProgressBar
            currentStep={currentStep}
            totalSteps={TOTAL_STEPS}
            title={STEP_TITLES[currentStep]}
          />
        </div>
      )}

      {/* Error message */}
      {error && (
        <div className="max-w-2xl mx-auto mb-4 p-3 bg-red-100 border border-red-300 rounded-xl">
          <p className="text-sm text-red-800">{error}</p>
        </div>
      )}

      {/* Steps */}
      {currentStep === 0 && (
        <StepWelcome onNext={() => setCurrentStep(1)} />
      )}

      {currentStep === 1 && (
        <StepOfficeInfo
          data={officeInfo}
          onUpdate={(d) => setOfficeInfo((prev) => ({ ...prev, ...d }))}
          onNext={handleSaveOfficeInfo}
          onBack={() => setCurrentStep(0)}
          loading={saving}
        />
      )}

      {currentStep === 2 && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 items-start">
          <StepSchedule
            data={schedule}
            onUpdate={(d) => setSchedule((prev) => ({ ...prev, ...d }))}
            onNext={handleSaveSchedule}
            onBack={() => setCurrentStep(1)}
            loading={saving}
          />
          <PreviewPane title="Vista previa">
            <SchedulePreview
              days={schedule.days}
              newPatientDuration={schedule.newPatientDuration}
              returningPatientDuration={schedule.returningPatientDuration}
              bufferMinutes={schedule.bufferMinutes}
            />
          </PreviewPane>
        </div>
      )}

      {currentStep === 3 && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 items-start">
          <StepConsultationDetails
            data={consultation}
            onUpdate={(d) => setConsultation((prev) => ({ ...prev, ...d }))}
            onNext={handleSaveConsultation}
            onBack={() => setCurrentStep(2)}
          />
          <PreviewPane title="Mensaje del bot">
            <ConsultationPreview
              first={consultation.newPatientCost}
              sub={consultation.returningPatientCost}
              insurance={consultation.acceptsInsurance}
              insurances={consultation.insuranceDetails}
            />
          </PreviewPane>
        </div>
      )}

      {currentStep === 4 && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 items-start">
          <StepPersonalize
            data={personalize}
            onUpdate={(d) => setPersonalize((prev) => ({ ...prev, ...d }))}
            onNext={handleSavePersonalize}
            onBack={() => setCurrentStep(3)}
            loading={saving}
          />
          <PreviewPane title="Personalidad">
            <AssistantPreview
              name={personalize.assistantName}
              tone={personalize.assistantTone}
              welcome={personalize.welcomeMessage}
            />
          </PreviewPane>
        </div>
      )}

      {currentStep === 5 && (
        <StepConnectWhatsApp
          onNext={() => setCurrentStep(6)}
          onBack={() => setCurrentStep(4)}
        />
      )}

      {currentStep === 6 && (
        <StepConnectCalendar
          onNext={() => setCurrentStep(7)}
          onBack={() => setCurrentStep(5)}
          connected={gcalConnected}
        />
      )}

      {currentStep === 7 && (
        <StepDone
          officeName={officeInfo.officeName || 'Tu consultorio'}
          onFinish={handleFinish}
          loading={saving}
        />
      )}
    </div>
  )
}
