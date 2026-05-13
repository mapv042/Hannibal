'use client'

import React, { useState } from 'react'
import { ProgressBar } from '@/components/onboarding/ProgressBar'
import { StepWelcome } from '@/components/onboarding/StepWelcome'
import { StepOfficeInfo, type OfficeInfoData } from '@/components/onboarding/StepOfficeInfo'
import { StepSchedule, type ScheduleData, type ScheduleDay } from '@/components/onboarding/StepSchedule'
import { StepConsultationDetails, type ConsultationData } from '@/components/onboarding/StepConsultationDetails'
import { StepPersonalize, type PersonalizeData } from '@/components/onboarding/StepPersonalize'
import { StepConnectWhatsApp } from '@/components/onboarding/StepConnectWhatsApp'
import { StepConnectCalendar } from '@/components/onboarding/StepConnectCalendar'
import { StepDone } from '@/components/onboarding/StepDone'

const TOTAL_STEPS = 7

function buildInitialScheduleDays(): ScheduleDay[] {
  return [0, 1, 2, 3, 4, 5, 6].map((dow) => ({
    dayOfWeek: dow,
    enabled: dow >= 1 && dow <= 5,
    blocks: dow >= 1 && dow <= 5
      ? [{ startTime: '09:00', endTime: '17:00' }]
      : [],
  }))
}

export default function OnboardingPreviewPage() {
  const [currentStep, setCurrentStep] = useState(0)

  const [officeInfo, setOfficeInfo] = useState<OfficeInfoData>({
    officeName: '',
    specialty: '',
    city: '',
    address: '',
    ownerPhone: '',
  })

  const [schedule, setSchedule] = useState<ScheduleData>({
    days: buildInitialScheduleDays(),
    appointmentDuration: 30,
    bufferMinutes: 10,
  })

  const [consultation, setConsultation] = useState<ConsultationData>({
    consultationCost: '',
    acceptsInsurance: '',
    insuranceDetails: '',
  })

  const [personalize, setPersonalize] = useState<PersonalizeData>({
    assistantName: '',
    assistantTone: 'formal',
    emergencySymptoms: '',
    welcomeMessage: '',
  })

  const next = () => setCurrentStep((s) => Math.min(s + 1, TOTAL_STEPS))
  const back = () => setCurrentStep((s) => Math.max(s - 1, 0))

  return (
    <div>
      {/* Preview banner */}
      <div className="mb-4 p-3 bg-yellow-100 border border-yellow-300 rounded-lg text-center">
        <p className="text-sm text-yellow-800 font-medium">
          Modo preview — los datos no se guardan
        </p>
      </div>

      {currentStep > 0 && currentStep < TOTAL_STEPS && (
        <ProgressBar currentStep={currentStep} totalSteps={TOTAL_STEPS} />
      )}

      {currentStep === 0 && (
        <StepWelcome onNext={next} />
      )}

      {currentStep === 1 && (
        <StepOfficeInfo
          data={officeInfo}
          onUpdate={(d) => setOfficeInfo((prev) => ({ ...prev, ...d }))}
          onNext={next}
          onBack={back}
          loading={false}
        />
      )}

      {currentStep === 2 && (
        <StepSchedule
          data={schedule}
          onUpdate={(d) => setSchedule((prev) => ({ ...prev, ...d }))}
          onNext={next}
          onBack={back}
          loading={false}
        />
      )}

      {currentStep === 3 && (
        <StepConsultationDetails
          data={consultation}
          onUpdate={(d) => setConsultation((prev) => ({ ...prev, ...d }))}
          onNext={next}
          onBack={back}
        />
      )}

      {currentStep === 4 && (
        <StepPersonalize
          data={personalize}
          onUpdate={(d) => setPersonalize((prev) => ({ ...prev, ...d }))}
          onNext={next}
          onBack={back}
          loading={false}
        />
      )}

      {currentStep === 5 && (
        <StepConnectWhatsApp
          onNext={next}
          onBack={back}
        />
      )}

      {currentStep === 6 && (
        <StepConnectCalendar
          onNext={next}
          onBack={back}
          connected={false}
        />
      )}

      {currentStep === 7 && (
        <StepDone
          officeName={officeInfo.officeName || 'Tu consultorio'}
          onFinish={() => alert('Preview — en produccion redirige al dashboard')}
          loading={false}
        />
      )}
    </div>
  )
}
