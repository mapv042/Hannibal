'use client'

import React, { useState } from 'react'
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
  officeInfo: { officeName: '', specialty: '', city: '', state: '', address: '', ownerPhone: '' },
  schedule: {
    days: buildInitialScheduleDays(),
    appointmentDuration: 30,
    newPatientDuration: 30,
    returningPatientDuration: 30,
    bufferMinutes: 10,
    reminders: { ...DEFAULT_REMINDER_TOGGLES },
  },
  consultation: { newPatientCost: '', returningPatientCost: '', acceptsInsurance: '', insuranceDetails: '' },
  personalize: { assistantName: '', assistantTone: 'formal', emergencySymptoms: '', welcomeMessage: '' },
}

/** A step submit handler returns false to stay on the step (e.g. on error). */
type SubmitHandler = (data: OnboardingData) => Promise<boolean | void> | boolean | void

interface OnboardingWizardProps {
  initialStep?: number
  initialData?: Partial<OnboardingData>
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

  const advance = () => setCurrentStep((s) => Math.min(s + 1, TOTAL_STEPS))
  const back = () => setCurrentStep((s) => Math.max(s - 1, 0))

  // Calls the (optional) submit handler with the latest data and advances
  // unless the handler explicitly returns false. Preview mode passes no
  // handler, so steps just navigate.
  const submit = (handler?: SubmitHandler) => async () => {
    if (!handler) {
      advance()
      return
    }
    const ok = await handler({ officeInfo, schedule, consultation, personalize })
    if (ok !== false) advance()
  }

  const usesPreview = currentStep === 2 || currentStep === 3 || currentStep === 4

  return (
    <div className={usesPreview ? 'w-full' : 'max-w-2xl mx-auto'}>
      {showPreviewBanner && (
        <div className="max-w-2xl mx-auto mb-4 p-3 bg-yellow-100 border border-yellow-300 rounded-xl text-center">
          <p className="text-sm text-yellow-800 font-medium">
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
        <div className="max-w-2xl mx-auto mb-4 p-3 bg-red-100 border border-red-300 rounded-xl">
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
            onNext={submit(onSubmitPersonalize)}
            onBack={back}
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

      {currentStep === 5 && <StepConnectWhatsApp onNext={advance} onBack={back} />}

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
