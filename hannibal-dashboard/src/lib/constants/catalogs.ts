/**
 * Shapes and ids for the onboarding catalogues.
 *
 * The lists themselves live in the backend (app/core/catalogs.py) and are
 * fetched at runtime, so the options the doctor picks from and the labels the
 * assistant later says to patients cannot drift apart. Only the ids that the
 * UI branches on are duplicated here.
 */

export const OTHER_SPECIALTY_ID = 'otra'

/**
 * Specialty ids only — the labels come from the API. Duplicated here because
 * re-hydrating the wizard has to tell "this is a catalogue id" from "this is
 * free text the doctor typed under Otra", and that check has to be synchronous.
 * Must stay in sync with SPECIALTIES in app/core/catalogs.py.
 */
export const SPECIALTY_IDS: string[] = [
  'oftalmologia',
  'medicina_general',
  'pediatria',
  'ginecologia',
  'dermatologia',
  'psicologia',
  'psiquiatria',
  'nutricion',
  'odontologia',
  'ortopedia',
  'cardiologia',
  'otorrinolaringologia',
  'gastroenterologia',
  'neurologia',
  'urologia',
  'endocrinologia',
  OTHER_SPECIALTY_ID,
]

export function isCatalogSpecialty(value: string | null | undefined): boolean {
  return !!value && SPECIALTY_IDS.includes(value)
}

export interface CatalogOption {
  id: string
  label: string
  description?: string
}

export interface OfficeService {
  name: string
  price: string
}

export type InsuranceChoice = '' | 'si' | 'algunos' | 'no'

export const ASSISTANT_GENDERS: CatalogOption[] = [
  { id: 'femenino', label: 'Femenino', description: '«Estoy lista para ayudarte»' },
  { id: 'masculino', label: 'Masculino', description: '«Estoy listo para ayudarte»' },
  { id: 'neutro', label: 'Neutro', description: '«Con gusto te ayudo»' },
]
