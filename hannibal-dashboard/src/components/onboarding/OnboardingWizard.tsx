'use client'

import React, { useEffect, useState } from 'react'
import { ProgressBar } from '@/components/onboarding/ProgressBar'
import { StepWelcome } from '@/components/onboarding/StepWelcome'
import { StepOfficeInfo, type OfficeInfoData } from '@/components/onboarding/StepOfficeInfo'
import {
  StepSchedule,
  type ScheduleData,
  type ScheduleDay,
  DEFAULT_REMINDER_TOGGLES,
} from '@/components/onboarding/StepSchedule'
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
import { useApi } from '@/lib/api'
import { STEP_VALIDATORS, type FieldErrors } from '@/lib/validation/onboarding'
import type { CatalogOption } from '@/lib/constants/catalogs'

export const TOTAL_STEPS = 7 // steps shown with progress bar (welcome = 0, done = 7)

const STEP_TITLES: Record<number, string> = {
  1: 'Tu consultorio',
  2: 'Horarios',
  3: 'Costos',
  4: 'Asistente',
  5: 'WhatsApp',
  6: 'Google Calendar',
}

export interface OnboardingData {
  officeInfo: OfficeInfoData
  schedule: ScheduleData
  consultation: ConsultationData
  personalize: PersonalizeData
}

export function buildInitialScheduleDays(): ScheduleDay[] {
  // 0=Sun … 6=Sat, Mon–Fri enabled by default
  return [0, 1, 2, 3, 4, 5, 6].map((dow) => ({
    dayOfWeek: dow,
    enabled: dow >= 1 && dow <= 5,
    blocks: dow >= 1 && dow <= 5 ? [{ startTime: '09:00', endTime: '17:00' }] : [],
  }))
}

const DEFAULTS: OnboardingData = {
  officeInfo: {
    doctorFirstName: '',
    doctorLastName: '',
    officeName: '',
    specialty: '',
    specialtyOther: '',
    city: '',
    state: '',
    address: '',
    ownerPhone: '',
    secondaryOwnerPhone: '',
  },
  schedule: {
    days: buildInitialScheduleDays(),
    appointmentDuration: 30,
    newPatientDuration: 30,
    returningPatientDuration: 30,
    bufferMinutes: 10,
    reminders: { ...DEFAULT_REMINDER_TOGGLES },
  },
  consultation: { services: [], acceptsInsurance: '', insurances: [] },
  personalize: {
    assistantName: '',
    assistantTone: 'formal',
    assistantGender: 'femenino',
    emergencySymptoms: [],
    intakeQuestions: [],
    intakeCustom: '',
    notifyNewAppointment: true,
    notifyCancellation: true,
    notifyNewPatient: true,
    notifyUnconfirmed: true,
    notifyArrival: true,
  },
}

/** A step submit handler returns false to stay on the step (e.g. on error). */
type SubmitHandler = (data: OnboardingData) => Promise<boolean | void> | boolean | void

interface OnboardingWizardProps {
  initialStep?: number
  initialData?: Partial<OnboardingData>
  /** Needed by the WhatsApp step; null/absent in preview mode. */
  officeId?: string | null
  gcalConnected?: boolean
  saving?: boolean
  error?: string
  showPreviewBanner?: boolean
  onSubmitOfficeInfo?: SubmitHandler
  onSubmitSchedule?: SubmitHandler
  onSubmitConsultation?: SubmitHandler
  onSubmitPersonalize?: SubmitHandler
  onFinish?: () => void
}

export function OnboardingWizard({
  initialStep = 0,
  initialData,
  officeId = null,
  gcalConnected = false,
  saving = false,
  error,
  showPreviewBanner = false,
  onSubmitOfficeInfo,
  onSubmitSchedule,
  onSubmitConsultation,
  onSubmitPersonalize,
  onFinish,
}: OnboardingWizardProps) {
  const [currentStep, setCurrentStep] = useState(initialStep)
  const [officeInfo, setOfficeInfo] = useState<OfficeInfoData>({
    ...DEFAULTS.officeInfo,
    ...initialData?.officeInfo,
  })
  const [schedule, setSchedule] = useState<ScheduleData>({
    ...DEFAULTS.schedule,
    ...initialData?.schedule,
  })
  const [consultation, setConsultation] = useState<ConsultationData>({
    ...DEFAULTS.consultation,
    ...initialData?.consultation,
  })
  const [personalize, setPersonalize] = useState<PersonalizeData>({
    ...DEFAULTS.personalize,
    ...initialData?.personalize,
  })

  const [errors, setErrors] = useState<FieldErrors>({})
  const [specialties, setSpecialties] = useState<CatalogOption[]>([])
  const [insurers, setInsurers] = useState<CatalogOption[]>([])
  const [intakeCatalog, setIntakeCatalog] = useState<CatalogOption[]>([])
  const [suggestedServices, setSuggestedServices] = useState<string[]>([])
  const [suggestedSymptoms, setSuggestedSymptoms] = useState<string[]>([])
  const api = useApi()

  // The three static catalogues: fetched once, needed from step 1 onwards.
  useEffect(() => {
    let cancelled = false
    void (async () => {
      const [s, i, q] = await Promise.all([
        api.getSpecialties(),
        api.getInsurers(),
        api.getIntakeQuestions(),
      ])
      if (cancelled) return
      if (s.data) setSpecialties(s.data.specialties)
      if (i.data) setInsurers(i.data.insurers)
      if (q.data) setIntakeCatalog(q.data.questions)
    })()
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // Suggestions depend on the chosen specialty, so they reload when it changes.
  // The doctor's own picks are never overwritten — only the list they pick from.
  useEffect(() => {
    if (!officeInfo.specialty) {
      setSuggestedServices([])
      setSuggestedSymptoms([])
      return
    }
    let cancelled = false
    void (async () => {
      const res = await api.getCatalogsBySpecialty(officeInfo.specialty)
      if (cancelled || !res.data) return
      setSuggestedServices(res.data.services)
      setSuggestedSymptoms(res.data.emergency_symptoms)
    })()
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [officeInfo.specialty])

  const advance = () => {
    setErrors({})
    setCurrentStep((s) => Math.min(s + 1, TOTAL_STEPS))
  }
  const back = () => {
    setErrors({})
    setCurrentStep((s) => Math.max(s - 1, 0))
  }

  /** Bring the first invalid field into view so the doctor sees what's missing. */
  const focusFirstInvalid = (fieldErrors: FieldErrors) => {
    if (typeof document === 'undefined') return
    const first = Object.keys(fieldErrors)[0]
    const el = document.querySelector<HTMLElement>(`[data-field="${first}"]`)
    if (!el) return
    el.scrollIntoView({ behavior: 'smooth', block: 'center' })
    el.focus?.()
  }

  // Validates the current step, then calls the (optional) submit handler with
  // the latest data and advances unless the handler explicitly returns false.
  // Validation runs first so an incomplete step never reaches the API — and it
  // runs in preview mode too (no handler), so the demo behaves like the real
  // thing.
  const submit = (handler?: SubmitHandler) => async () => {
    const data = { officeInfo, schedule, consultation, personalize }
    const fieldErrors = STEP_VALIDATORS[currentStep]?.(data) ?? {}
    if (Object.keys(fieldErrors).length > 0) {
      setErrors(fieldErrors)
      focusFirstInvalid(fieldErrors)
      return
    }
    setErrors({})

    if (!handler) {
      advance()
      return
    }
    const ok = await handler(data)
    if (ok !== false) advance()
  }

  const usesPreview = currentStep === 2 || currentStep === 3 || currentStep === 4

  return (
    <div className={usesPreview ? 'w-full' : 'max-w-2xl mx-auto'}>
      {showPreviewBanner && (
        <div className="max-w-2xl mx-auto mb-4 p-3 bg-amber-50 border border-amber-200 rounded-lg text-center">
          <p className="text-sm text-amber-800 font-medium">
            Modo preview — los datos no se guardan
          </p>
        </div>
      )}

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
        <div className="max-w-2xl mx-auto mb-4 p-3 bg-red-50 border border-red-200 rounded-lg">
          <p className="text-sm text-red-800">{error}</p>
        </div>
      )}

      {currentStep === 0 && <StepWelcome onNext={advance} />}

      {currentStep === 1 && (
        <StepOfficeInfo
          data={officeInfo}
          onUpdate={(d) => setOfficeInfo((prev) => ({ ...prev, ...d }))}
          onNext={submit(onSubmitOfficeInfo)}
          onBack={back}
          loading={saving}
          errors={errors}
          specialties={specialties}
        />
      )}

      {currentStep === 2 && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 items-start">
          <StepSchedule
            data={schedule}
            onUpdate={(d) => setSchedule((prev) => ({ ...prev, ...d }))}
            onNext={submit(onSubmitSchedule)}
            onBack={back}
            loading={saving}
            errors={errors}
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
            onNext={submit(onSubmitConsultation)}
            onBack={back}
            errors={errors}
            suggestedServices={suggestedServices}
            insurers={insurers}
          />
          <PreviewPane title="Mensaje del bot">
            <ConsultationPreview
              services={consultation.services}
              insurance={consultation.acceptsInsurance}
              insurerNames={insurers
                .filter((i) => consultation.insurances.includes(i.id))
                .map((i) => i.label)}
            />
          </PreviewPane>
        </div>
      )}

      {currentStep === 4 && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 items-start">
          <StepPersonalize
            data={personalize}
            onUpdate={(d) => setPersonalize((prev) => ({ ...prev, ...d }))}
            onNext={submit(onSubmitPersonalize)}
            onBack={back}
            loading={saving}
            errors={errors}
            suggestedSymptoms={suggestedSymptoms}
            intakeCatalog={intakeCatalog}
          />
          <PreviewPane title="Personalidad">
            <AssistantPreview
              name={personalize.assistantName}
              tone={personalize.assistantTone}
              officeName={officeInfo.officeName}
            />
          </PreviewPane>
        </div>
      )}

      {currentStep === 5 && (
        <StepConnectWhatsApp onNext={advance} onBack={back} officeId={officeId} />
      )}

      {currentStep === 6 && (
        <StepConnectCalendar onNext={advance} onBack={back} connected={gcalConnected} />
      )}

      {currentStep === 7 && (
        <StepDone
          officeName={officeInfo.officeName || 'Tu consultorio'}
          onFinish={onFinish ?? (() => {})}
          loading={saving}
        />
      )}
    </div>
  )
}
