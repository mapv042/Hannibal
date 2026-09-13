/**
 * Per-step validation for the onboarding wizard.
 *
 * Pure functions: each takes the wizard's data and returns a map of field name
 * to error message, empty when the step is complete. The wizard runs the
 * matching validator before calling the step's submit handler, so an incomplete
 * step never reaches the API.
 *
 * These mirror `_assert_office_complete` in the backend
 * (app/modules/offices/service.py). That one is the real gate — this one exists
 * so the doctor sees which field is missing instead of a rejected request.
 */

import type { OnboardingData } from '@/components/onboarding/OnboardingWizard'
import { OTHER_SPECIALTY_ID } from '@/lib/constants/catalogs'

export type FieldErrors = Record<string, string>

const REQUIRED = 'Este campo es obligatorio'

/** Mexican mobile numbers are 10 digits; a +52 prefix is accepted and ignored. */
export function isValidMxPhone(raw: string): boolean {
  const digits = raw.replace(/\D/g, '')
  if (digits.length === 10) return true
  // 52 + 10 digits, with or without the legacy "1" Meta sometimes prepends.
  if (digits.length === 12 && digits.startsWith('52')) return true
  if (digits.length === 13 && digits.startsWith('521')) return true
  return false
}

function requireText(value: string | undefined, errors: FieldErrors, field: string) {
  if (!value || !value.trim()) errors[field] = REQUIRED
}

export function validateOfficeInfo(data: OnboardingData): FieldErrors {
  const errors: FieldErrors = {}
  const o = data.officeInfo

  requireText(o.doctorFirstName, errors, 'doctorFirstName')
  requireText(o.doctorLastName, errors, 'doctorLastName')
  requireText(o.officeName, errors, 'officeName')
  requireText(o.specialty, errors, 'specialty')
  requireText(o.city, errors, 'city')
  requireText(o.state, errors, 'state')
  requireText(o.address, errors, 'address')

  // "Otra" is a real choice, but then we need to know which one.
  if (o.specialty === OTHER_SPECIALTY_ID && !o.specialtyOther?.trim()) {
    errors.specialtyOther = '¿Cuál es tu especialidad?'
  }

  if (!o.ownerPhone?.trim()) {
    errors.ownerPhone = REQUIRED
  } else if (!isValidMxPhone(o.ownerPhone)) {
    errors.ownerPhone = 'Escribe un número de 10 dígitos'
  }

  // Optional, but a typo here means the secretary silently gets nothing.
  if (o.secondaryOwnerPhone?.trim() && !isValidMxPhone(o.secondaryOwnerPhone)) {
    errors.secondaryOwnerPhone = 'Escribe un número de 10 dígitos'
  }

  return errors
}

export function validateSchedule(data: OnboardingData): FieldErrors {
  const errors: FieldErrors = {}
  const days = data.schedule.days

  const active = days.filter((d) => d.enabled && d.blocks.length > 0)
  if (active.length === 0) {
    errors.days = 'Activa al menos un día con un horario'
    return errors
  }

  for (const day of active) {
    for (const block of day.blocks) {
      if (!block.startTime || !block.endTime) {
        errors.days = 'Completa la hora de inicio y de fin en todos los bloques'
        return errors
      }
      if (block.endTime <= block.startTime) {
        errors.days = 'La hora de fin debe ser posterior a la de inicio'
        return errors
      }
    }
    // Overlapping blocks silently double-book the same hour.
    const sorted = [...day.blocks].sort((a, b) => a.startTime.localeCompare(b.startTime))
    for (let i = 1; i < sorted.length; i++) {
      if (sorted[i].startTime < sorted[i - 1].endTime) {
        errors.days = 'Hay bloques encimados en el mismo día'
        return errors
      }
    }
  }

  return errors
}

export function validateConsultation(data: OnboardingData): FieldErrors {
  const errors: FieldErrors = {}
  const c = data.consultation

  const withName = c.services.filter((s) => s.name.trim())
  if (withName.length === 0) {
    errors.services = 'Agrega al menos un servicio'
  } else if (withName.some((s) => !s.price.trim())) {
    errors.services = 'Ponle precio a cada servicio seleccionado'
  }

  if (!c.acceptsInsurance) {
    errors.acceptsInsurance = 'Elige una opción'
  } else if (
    (c.acceptsInsurance === 'si' || c.acceptsInsurance === 'algunos') &&
    c.insurances.length === 0
  ) {
    errors.insurances = 'Selecciona al menos una aseguradora'
  }

  return errors
}

export function validatePersonalize(data: OnboardingData): FieldErrors {
  const errors: FieldErrors = {}
  const p = data.personalize

  requireText(p.assistantName, errors, 'assistantName')
  if (!p.assistantTone) errors.assistantTone = 'Elige un tono'
  if (!p.assistantGender) errors.assistantGender = 'Elige una opción'

  if (p.emergencySymptoms.length === 0) {
    errors.emergencySymptoms = 'Selecciona al menos un síntoma de alarma'
  }
  if (p.intakeQuestions.length === 0 && !p.intakeCustom.trim()) {
    errors.intakeQuestions = 'Elige al menos una pregunta'
  }

  return errors
}

/** Validator per wizard step index; steps without one never block. */
export const STEP_VALIDATORS: Record<number, (data: OnboardingData) => FieldErrors> = {
  1: validateOfficeInfo,
  2: validateSchedule,
  3: validateConsultation,
  4: validatePersonalize,
}
