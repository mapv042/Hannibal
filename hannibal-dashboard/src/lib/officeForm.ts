/**
 * The office form, shared by onboarding and Settings.
 *
 * Both screens edit the same office with the same step components; these
 * helpers are the one place that maps between the API's Office and the form's
 * data, so what the wizard saved is exactly what Settings loads back.
 */

import {
  buildInitialScheduleDays,
  type OnboardingData,
} from '@/components/onboarding/OnboardingWizard'
import type { OfficeInfoData } from '@/components/onboarding/StepOfficeInfo'
import type { ConsultationData } from '@/components/onboarding/StepConsultationDetails'
import type { PersonalizeData } from '@/components/onboarding/StepPersonalize'
import {
  reminderTogglesFromRules,
  type ScheduleData,
  type ScheduleDay,
} from '@/components/onboarding/StepSchedule'
import {
  OTHER_SPECIALTY_ID,
  isCatalogSpecialty,
  type InsuranceChoice,
} from '@/lib/constants/catalogs'
import type { ReminderRule } from '@/lib/api'
import type { AvailabilitySchedule, Office } from '@/lib/supabase'

/** "09:00:00" → "09:00" (what <input type="time"> expects). */
const hhmm = (value: string) => value.slice(0, 5)

/** Weekly schedule rows from the API → the form's seven days. */
export function scheduleDaysFromRows(rows: AvailabilitySchedule[]): ScheduleDay[] {
  const active = rows.filter((r) => r.is_active !== false)
  if (active.length === 0) return buildInitialScheduleDays()
  return [0, 1, 2, 3, 4, 5, 6].map((dow) => {
    const blocks = active
      .filter((r) => r.day_of_week === dow)
      .map((r) => ({ startTime: hhmm(r.start_time), endTime: hhmm(r.end_time) }))
      .sort((a, b) => a.startTime.localeCompare(b.startTime))
    return { dayOfWeek: dow, enabled: blocks.length > 0, blocks }
  })
}

export function formDataFromOffice(
  office: Office,
  reminderRules?: ReminderRule[] | null,
  schedules?: AvailabilitySchedule[] | null
): Partial<OnboardingData> {
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
      privacyContactEmail: office.privacy_contact_email || '',
    },
    schedule: {
      days: schedules?.length ? scheduleDaysFromRows(schedules) : buildInitialScheduleDays(),
      appointmentDuration: Math.max(
        office.new_patient_duration_min || 30,
        office.returning_patient_duration_min || 30
      ),
      newPatientDuration: office.new_patient_duration_min || 30,
      returningPatientDuration: office.returning_patient_duration_min || 30,
      bufferMinutes: schedules?.[0]?.buffer_minutes ?? 10,
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
}

export function officeInfoPayload(officeInfo: OfficeInfoData) {
  // "Otra" stores what the doctor typed; anything else stores the id.
  const specialty =
    officeInfo.specialty === OTHER_SPECIALTY_ID
      ? officeInfo.specialtyOther.trim()
      : officeInfo.specialty

  return {
    name: officeInfo.officeName,
    doctor_first_name: officeInfo.doctorFirstName || undefined,
    doctor_last_name: officeInfo.doctorLastName || undefined,
    specialty: specialty || undefined,
    city: officeInfo.city || undefined,
    state: officeInfo.state || undefined,
    address: officeInfo.address || undefined,
    owner_phone: officeInfo.ownerPhone || undefined,
    // Empty string clears a previously saved second number / email.
    secondary_owner_phone: officeInfo.secondaryOwnerPhone.trim(),
    privacy_contact_email: officeInfo.privacyContactEmail.trim(),
  }
}

/** The weekly schedule rows PUT /api/scheduling/schedules replaces wholesale. */
export function schedulesPayload(schedule: ScheduleData) {
  return schedule.days
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
}

export function durationsPayload(schedule: ScheduleData): Partial<Office> {
  return {
    new_patient_duration_min: schedule.newPatientDuration,
    returning_patient_duration_min: schedule.returningPatientDuration,
  }
}

export function consultationPayload(consultation: ConsultationData): Partial<Office> {
  const services = consultation.services.filter((s) => s.name.trim())
  // The two generic consultations keep feeding the prompt's PACIENTE
  // ACTUAL block, which quotes the price for this patient's visit type.
  const priceOf = (name: string) => services.find((s) => s.name === name)?.price || undefined

  return {
    services,
    accepts_insurance: consultation.acceptsInsurance || undefined,
    insurances: consultation.insurances,
    new_patient_cost: priceOf('Primera consulta'),
    returning_patient_cost: priceOf('Consulta subsecuente'),
  } as Partial<Office>
}

/** Alarm symptoms and intake questions — what the assistant watches for and asks. */
export function screeningPayload(personalize: PersonalizeData): Partial<Office> {
  return {
    emergency_symptoms: personalize.emergencySymptoms.filter((s) => s.trim()),
    intake_questions: {
      preset: personalize.intakeQuestions,
      custom: personalize.intakeCustom.trim() || null,
    },
  }
}

export function personalizePayload(personalize: PersonalizeData): Partial<Office> {
  return {
    assistant_name: personalize.assistantName,
    assistant_tone: personalize.assistantTone,
    assistant_gender: personalize.assistantGender,
    ...screeningPayload(personalize),
    notify_new_appointment: personalize.notifyNewAppointment,
    notify_cancellation: personalize.notifyCancellation,
    notify_new_patient: personalize.notifyNewPatient,
    notify_unconfirmed: personalize.notifyUnconfirmed,
    notify_arrival: personalize.notifyArrival,
  }
}
