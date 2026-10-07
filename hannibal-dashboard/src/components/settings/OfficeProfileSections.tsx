'use client'

import React, { useEffect, useState } from 'react'
import { useApi } from '@/lib/api'
import { Card, CardBody, CardHeader } from '@/components/ui/Card'
import { StepOfficeInfo, type OfficeInfoData } from '@/components/onboarding/StepOfficeInfo'
import { StepSchedule, type ScheduleData } from '@/components/onboarding/StepSchedule'
import {
  StepConsultationDetails,
  type ConsultationData,
} from '@/components/onboarding/StepConsultationDetails'
import { StepPersonalize, type PersonalizeData } from '@/components/onboarding/StepPersonalize'
import type { OnboardingData } from '@/components/onboarding/OnboardingWizard'
import {
  consultationPayload,
  durationsPayload,
  formDataFromOffice,
  officeInfoPayload,
  schedulesPayload,
  screeningPayload,
} from '@/lib/officeForm'
import {
  validateConsultation,
  validateOfficeInfo,
  validatePersonalize,
  validateSchedule,
  type FieldErrors,
} from '@/lib/validation/onboarding'
import type { CatalogOption } from '@/lib/constants/catalogs'
import type { AvailabilitySchedule, Office } from '@/lib/supabase'
import { Building2, Clock, Receipt, Siren, type LucideIcon } from 'lucide-react'

type SectionKey = 'officeInfo' | 'schedule' | 'consultation' | 'screening'

interface SectionState {
  saving: boolean
  saved: boolean
  error: string
  fieldErrors: FieldErrors
}

const IDLE: SectionState = { saving: false, saved: false, error: '', fieldErrors: {} }

interface OfficeProfileSectionsProps {
  office: Office
  onOfficeUpdated: (office: Office) => void
}

function Section({
  icon: Icon,
  title,
  subtitle,
  state,
  children,
}: {
  icon: LucideIcon
  title: string
  subtitle: string
  state: SectionState
  children: React.ReactNode
}) {
  return (
    <Card>
      <CardHeader>
        <div className="flex items-center gap-3.5">
          <div className="w-10 h-10 rounded-[10px] bg-primary-50 flex items-center justify-center flex-shrink-0">
            <Icon size={20} className="text-primary-700" />
          </div>
          <div>
            <h2 className="text-base font-semibold tracking-tight text-gray-900">{title}</h2>
            <p className="text-[13px] text-gray-500 mt-0.5">{subtitle}</p>
          </div>
        </div>
      </CardHeader>
      <CardBody className="space-y-4">
        {state.saved && (
          <div className="p-3 bg-green-100 border border-green-300 rounded-xl">
            <p className="text-sm text-green-800">Cambios guardados. Tu asistente ya los usa.</p>
          </div>
        )}
        {state.error && (
          <div className="p-3 bg-red-100 border border-red-300 rounded-xl">
            <p className="text-sm text-red-800">{state.error}</p>
          </div>
        )}
        {children}
      </CardBody>
    </Card>
  )
}

/**
 * Everything the doctor configured during onboarding, editable afterwards with
 * the very same step components. Each section saves on its own and runs the
 * onboarding validator for its slice, so Settings can never store an office
 * the wizard would have refused.
 */
export function OfficeProfileSections({ office, onOfficeUpdated }: OfficeProfileSectionsProps) {
  const api = useApi()
  const [form, setForm] = useState<OnboardingData | null>(null)
  const [sections, setSections] = useState<Record<SectionKey, SectionState>>({
    officeInfo: IDLE,
    schedule: IDLE,
    consultation: IDLE,
    screening: IDLE,
  })

  const [specialties, setSpecialties] = useState<CatalogOption[]>([])
  const [insurers, setInsurers] = useState<CatalogOption[]>([])
  const [intakeCatalog, setIntakeCatalog] = useState<CatalogOption[]>([])
  const [suggestedServices, setSuggestedServices] = useState<string[]>([])
  const [suggestedSymptoms, setSuggestedSymptoms] = useState<string[]>([])

  // Form data and the static catalogues, loaded once.
  useEffect(() => {
    let cancelled = false
    void (async () => {
      const [schedulesRes, rulesRes, s, i, q] = await Promise.all([
        api.getAvailabilitySchedules(),
        api.getReminderRules(office.id),
        api.getSpecialties(),
        api.getInsurers(),
        api.getIntakeQuestions(),
      ])
      if (cancelled) return
      const schedules: AvailabilitySchedule[] = schedulesRes.data ?? []
      const data = formDataFromOffice(office, rulesRes.data, schedules)
      setForm({
        officeInfo: data.officeInfo!,
        schedule: data.schedule!,
        consultation: data.consultation!,
        personalize: data.personalize ?? {
          assistantName: office.assistant_name,
          assistantTone: office.assistant_tone as 'formal' | 'informal',
          assistantGender: office.assistant_gender,
          emergencySymptoms: office.emergency_symptoms || [],
          intakeQuestions: office.intake_questions?.preset || [],
          intakeCustom: office.intake_questions?.custom || '',
          notifyNewAppointment: office.notify_new_appointment,
          notifyCancellation: office.notify_cancellation,
          notifyNewPatient: office.notify_new_patient,
          notifyUnconfirmed: office.notify_unconfirmed,
          notifyArrival: office.notify_arrival,
        },
      })
      if (s.data) setSpecialties(s.data.specialties)
      if (i.data) setInsurers(i.data.insurers)
      if (q.data) setIntakeCatalog(q.data.questions)
    })()
    return () => {
      cancelled = true
    }
    // Loaded once per office; later edits live in local state.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [office.id])

  // Specialty-driven suggestions, reloaded when the doctor changes specialty.
  const specialty = form?.officeInfo.specialty
  useEffect(() => {
    if (!specialty) return
    let cancelled = false
    void (async () => {
      const res = await api.getCatalogsBySpecialty(specialty)
      if (cancelled || !res.data) return
      setSuggestedServices(res.data.services)
      setSuggestedSymptoms(res.data.emergency_symptoms)
    })()
    return () => {
      cancelled = true
    }
  }, [api, specialty])

  if (!form) {
    return (
      <Card>
        <CardBody>
          <p className="text-sm text-gray-600">Cargando datos del consultorio...</p>
        </CardBody>
      </Card>
    )
  }

  const setSection = (key: SectionKey, patch: Partial<SectionState>) =>
    setSections((prev) => ({ ...prev, [key]: { ...prev[key], ...patch } }))

  /** Validate a slice, run its save, and report the outcome in its own section. */
  const save = async (
    key: SectionKey,
    validate: (data: OnboardingData) => FieldErrors,
    persist: () => Promise<Office | null>
  ) => {
    const fieldErrors = validate(form)
    if (Object.keys(fieldErrors).length > 0) {
      setSection(key, { ...IDLE, fieldErrors, error: 'Revisa los campos marcados.' })
      return
    }
    setSection(key, { ...IDLE, saving: true })
    try {
      const updated = await persist()
      if (updated) onOfficeUpdated(updated)
      setSection(key, { ...IDLE, saved: true })
      setTimeout(() => setSection(key, { saved: false }), 3000)
    } catch (err) {
      setSection(key, {
        ...IDLE,
        error: err instanceof Error ? err.message : 'No se pudieron guardar los cambios.',
      })
    }
  }

  const updateOffice = async (payload: Partial<Office>): Promise<Office> => {
    const res = await api.updateOffice(office.id, payload)
    if (!res.success || !res.data) throw new Error(res.error || 'No se pudieron guardar los cambios.')
    return res.data
  }

  const update = <K extends keyof OnboardingData>(key: K, patch: Partial<OnboardingData[K]>) =>
    setForm((prev) => (prev ? { ...prev, [key]: { ...prev[key], ...patch } } : prev))

  const noop = () => {}

  return (
    <>
      <Section
        icon={Building2}
        title="Tu consultorio"
        subtitle="Datos que tu asistente usa para presentarse y dar la dirección."
        state={sections.officeInfo}
      >
        <p className="text-sm text-gray-600">
          Tus pacientes aceptan tu{' '}
          <a
            href={`/aviso/${office.id}`}
            target="_blank"
            rel="noopener noreferrer"
            className="text-primary-700 font-medium hover:underline"
          >
            aviso de privacidad
          </a>{' '}
          antes de agendar por WhatsApp. Se arma con los datos de esta sección.
        </p>
        <StepOfficeInfo
          variant="settings"
          data={form.officeInfo}
          onUpdate={(d: Partial<OfficeInfoData>) => update('officeInfo', d)}
          onNext={() =>
            save('officeInfo', validateOfficeInfo, () =>
              updateOffice(officeInfoPayload(form.officeInfo) as Partial<Office>)
            )
          }
          onBack={noop}
          loading={sections.officeInfo.saving}
          errors={sections.officeInfo.fieldErrors}
          specialties={specialties}
        />
      </Section>

      <Section
        icon={Clock}
        title="Horarios de atención"
        subtitle="El asistente solo ofrece citas dentro de estos bloques. Para un día o unas horas sueltas, pídele que bloquee el horario por WhatsApp."
        state={sections.schedule}
      >
        <StepSchedule
          variant="settings"
          data={form.schedule}
          onUpdate={(d: Partial<ScheduleData>) => update('schedule', d)}
          onNext={() =>
            save('schedule', validateSchedule, async () => {
              const res = await api.upsertAvailabilitySchedules(schedulesPayload(form.schedule))
              if (!res.success) throw new Error(res.error || 'No se pudieron guardar los horarios.')
              return updateOffice(durationsPayload(form.schedule))
            })
          }
          onBack={noop}
          loading={sections.schedule.saving}
          errors={sections.schedule.fieldErrors}
        />
      </Section>

      <Section
        icon={Receipt}
        title="Servicios, precios y seguros"
        subtitle="Lo que tu asistente contesta cuando un paciente pregunta cuánto cuesta o si aceptas su seguro."
        state={sections.consultation}
      >
        <StepConsultationDetails
          variant="settings"
          data={form.consultation}
          onUpdate={(d: Partial<ConsultationData>) => update('consultation', d)}
          onNext={() =>
            save('consultation', validateConsultation, () =>
              updateOffice(consultationPayload(form.consultation))
            )
          }
          onBack={noop}
          loading={sections.consultation.saving}
          errors={sections.consultation.fieldErrors}
          suggestedServices={suggestedServices}
          insurers={insurers}
        />
      </Section>

      <Section
        icon={Siren}
        title="Urgencias y preguntas previas"
        subtitle="Qué síntomas te avisa de inmediato tu asistente y qué le pregunta al paciente antes de la cita."
        state={sections.screening}
      >
        <StepPersonalize
          variant="settings"
          data={form.personalize}
          onUpdate={(d: Partial<PersonalizeData>) => update('personalize', d)}
          onNext={() =>
            save('screening', validatePersonalize, () =>
              updateOffice(screeningPayload(form.personalize))
            )
          }
          onBack={noop}
          loading={sections.screening.saving}
          errors={sections.screening.fieldErrors}
          suggestedSymptoms={suggestedSymptoms}
          intakeCatalog={intakeCatalog}
        />
      </Section>
    </>
  )
}
